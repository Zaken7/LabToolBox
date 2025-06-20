#!/usr/bin/env python3
"""
Kubernetes Secret Creator Script with SOPS Encryption

This script creates Kubernetes secrets from user-provided key/value pairs.
Supports optional SOPS encryption for the data fields.

Usage: python3 create_k8s_secret.py

Input format: KEY1: "VALUE1"; KEY2: "VALUE2"; KEY3: "VALUE3"
Example: username: "admin"; password: "secret123"; api_key: "abc123xyz"
"""

import subprocess
import sys
import re
import shlex
import os
import tempfile
import shutil
from typing import Dict, Tuple, Optional, List


def check_sops_availability() -> bool:
    """
    Check if SOPS command is available in the system.
    
    Returns:
        bool: True if SOPS is available, False otherwise
    """
    try:
        subprocess.run(["sops", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def install_sops_prompt() -> bool:
    """
    Prompt user to install SOPS and provide installation instructions.
    
    Returns:
        bool: True if user wants to continue without SOPS, False to exit
    """
    print("\n⚠️  SOPS not found on your system!")
    print("SOPS is required for encrypting secrets.")
    print("\nInstallation options:")
    print("1. Using Homebrew: brew install sops")
    print("2. Using apt (if available): sudo apt install sops")
    print("3. Download from GitHub: https://github.com/mozilla/sops/releases")
    print("4. Using go: go install go.mozilla.org/sops/v3/cmd/sops@latest")
    
    while True:
        choice = input("\nOptions:\n1. Continue without SOPS encryption\n2. Exit to install SOPS\nChoose (1/2): ").strip()
        if choice == '1':
            return True
        elif choice == '2':
            return False
        else:
            print("Please enter 1 or 2.")


def get_age_public_key() -> str:
    """
    Get AGE public key from user with validation.
    
    Returns:
        str: Valid AGE public key
    """
    print("\nEnter your AGE public key for SOPS encryption:")
    print("Example: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    
    while True:
        age_key = input("AGE public key: ").strip()
        
        # Validate AGE key format
        if re.match(r'^age1[a-z0-9]{58}$', age_key):
            return age_key
        else:
            print("Invalid AGE key format. Should start with 'age1' followed by 58 characters.")


def parse_key_value_input(user_input: str) -> Dict[str, str]:
    """
    Parse user input string containing key/value pairs separated by semicolons.
    
    Args:
        user_input (str): Input string like 'KEY1: "VALUE1"; KEY2: "VALUE2"'
    
    Returns:
        Dict[str, str]: Dictionary of parsed key/value pairs
    
    Raises:
        ValueError: If input format is invalid
    """
    if not user_input.strip():
        raise ValueError("Input cannot be empty")
    
    pairs = {}
    
    # Split by semicolon and process each pair
    for pair in user_input.split(';'):
        pair = pair.strip()
        if not pair:
            continue
            
        # Match pattern: KEY: "VALUE" or KEY: 'VALUE' or KEY: VALUE
        match = re.match(r'^([^:]+):\s*["\']?([^"\']*)["\']?$', pair)
        if not match:
            raise ValueError(f"Invalid format for pair: '{pair}'. Expected format: KEY: \"VALUE\"")
        
        key = match.group(1).strip()
        value = match.group(2).strip()
        
        # Validate key (must be valid for Kubernetes)
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.-]*$', key):
            raise ValueError(f"Invalid key '{key}'. Keys must start with a letter or underscore and contain only alphanumeric characters, dots, dashes, and underscores.")
        
        pairs[key] = value
    
    if not pairs:
        raise ValueError("No valid key/value pairs found")
    
    return pairs


def get_user_inputs() -> Tuple[str, str, Dict[str, str], bool, Optional[str]]:
    """
    Get secret name, namespace, key/value pairs, and SOPS options from user.
    
    Returns:
        Tuple[str, str, Dict[str, str], bool, Optional[str]]: 
        secret_name, namespace, key_value_pairs, use_sops, age_key
    """
    print("Kubernetes Secret Creator with SOPS Encryption")
    print("=" * 50)
    
    # Get secret name
    while True:
        secret_name = input("Enter secret name: ").strip()
        if secret_name and re.match(r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$', secret_name):
            break
        print("Invalid secret name. Must be lowercase alphanumeric with hyphens, starting and ending with alphanumeric.")
    
    # Get namespace (optional)
    namespace = input("Enter namespace (press Enter for 'default'): ").strip()
    if not namespace:
        namespace = "default"
    elif not re.match(r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$', namespace):
        print("Invalid namespace name. Using 'default'.")
        namespace = "default"
    
    # Check SOPS availability and ask user preference
    sops_available = check_sops_availability()
    use_sops = False
    age_key = None
    
    if sops_available:
        while True:
            sops_choice = input("\nDo you want to use SOPS encryption for the secret data? (y/n): ").strip().lower()
            if sops_choice in ['y', 'yes']:
                use_sops = True
                age_key = get_age_public_key()
                break
            elif sops_choice in ['n', 'no']:
                use_sops = False
                break
            else:
                print("Please enter 'y' or 'n'.")
    else:
        # SOPS not available, ask user what to do
        continue_without_sops = install_sops_prompt()
        if not continue_without_sops:
            print("Exiting to allow SOPS installation.")
            sys.exit(0)
    
    # Get key/value pairs
    print("\nEnter key/value pairs in the format: KEY1: \"VALUE1\"; KEY2: \"VALUE2\"")
    print("Example: username: \"admin\"; password: \"secret123\"; api_key: \"abc123xyz\"")
    
    while True:
        try:
            kv_input = input("\nKey/Value pairs: ").strip()
            key_value_pairs = parse_key_value_input(kv_input)
            break
        except ValueError as e:
            print(f"Error: {e}")
            print("Please try again.")
    
    return secret_name, namespace, key_value_pairs, use_sops, age_key


def create_kubectl_command(secret_name: str, namespace: str, key_value_pairs: Dict[str, str]) -> list:
    """
    Create kubectl command to create the secret.
    
    Args:
        secret_name (str): Name of the secret
        namespace (str): Kubernetes namespace
        key_value_pairs (Dict[str, str]): Dictionary of key/value pairs
    
    Returns:
        list: kubectl command as a list of strings
    """
    cmd = [
        "kubectl", "create", "secret", "generic", secret_name,
        "--namespace", namespace
    ]
    
    # Add each key/value pair as --from-literal
    for key, value in key_value_pairs.items():
        cmd.extend(["--from-literal", f"{key}={value}"])
    
    return cmd


def encrypt_with_sops(yaml_content: str, age_key: str) -> str:
    """
    Encrypt YAML content using SOPS with AGE encryption.
    
    Args:
        yaml_content (str): Plain YAML content
        age_key (str): AGE public key
    
    Returns:
        str: SOPS-encrypted YAML content
    
    Raises:
        subprocess.CalledProcessError: If SOPS encryption fails
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
        temp_file.write(yaml_content)
        temp_file_path = temp_file.name
    
    try:
        # Create SOPS command
        sops_cmd = [
            "sops", "--encrypt", 
            "--age", age_key,
            "--encrypted-regex", "^(data|stringData)$",
            temp_file_path
        ]
        
        result = subprocess.run(sops_cmd, capture_output=True, text=True, check=True)
        return result.stdout
        
    finally:
        # Clean up temporary file
        os.unlink(temp_file_path)


def save_yaml_to_file(yaml_content: str, secret_name: str, file_suffix: str = "") -> str:
    """
    Save YAML content to a file named after the secret.
    
    Args:
        yaml_content (str): The YAML content to save
        secret_name (str): Name of the secret (used for filename)
        file_suffix (str): Additional suffix for filename (e.g., "-sops")
    
    Returns:
        str: Path to the saved file
    
    Raises:
        IOError: If file cannot be written
    """
    filename = f"{secret_name}-secret{file_suffix}.yaml"
    
    # Ensure we don't overwrite existing files
    counter = 1
    original_filename = filename
    while os.path.exists(filename):
        name, ext = os.path.splitext(original_filename)
        filename = f"{name}-{counter}{ext}"
        counter += 1
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        return filename
    except IOError as e:
        raise IOError(f"Failed to write file '{filename}': {e}")


def run_kubectl_command(cmd: list, secret_name: str, use_sops: bool = False, age_key: Optional[str] = None, dry_run: bool = False) -> bool:
    """
    Execute the kubectl command.
    
    Args:
        cmd (list): kubectl command as list of strings
        secret_name (str): Name of the secret (used for filename in dry-run)
        use_sops (bool): Whether to use SOPS encryption
        age_key (Optional[str]): AGE public key for SOPS
        dry_run (bool): If True, add --dry-run=client flag and save to file
    
    Returns:
        bool: True if successful, False otherwise
    """
    if dry_run:
        cmd.extend(["--dry-run=client", "-o", "yaml"])
    
    try:
        print(f"\nExecuting command:")
        # Print command with proper shell escaping for display
        print(" ".join(shlex.quote(arg) for arg in cmd))
        print()
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        if dry_run:
            print("Dry run completed successfully!")
            
            yaml_content = result.stdout
            saved_files = []
            
            # Always save the plain YAML file first
            try:
                plain_filename = save_yaml_to_file(yaml_content, secret_name)
                saved_files.append(plain_filename)
                print(f"✅ Plain YAML saved to: {plain_filename}")
            except IOError as e:
                print(f"❌ Failed to save plain YAML: {e}")
            
            # Apply SOPS encryption if requested and save encrypted version
            if use_sops and age_key:
                try:
                    print("Encrypting with SOPS...")
                    encrypted_yaml = encrypt_with_sops(yaml_content, age_key)
                    
                    # Save encrypted version
                    encrypted_filename = save_yaml_to_file(encrypted_yaml, secret_name, "-sops")
                    saved_files.append(encrypted_filename)
                    print(f"✅ SOPS-encrypted YAML saved to: {encrypted_filename}")
                    
                except subprocess.CalledProcessError as e:
                    print(f"❌ SOPS encryption failed: {e}")
                    if e.stderr:
                        print(f"SOPS error: {e.stderr}")
                except IOError as e:
                    print(f"❌ Failed to save encrypted YAML: {e}")
            
            # Show summary of saved files
            if saved_files:
                print(f"\n📁 Files saved:")
                for filename in saved_files:
                    file_size = os.path.getsize(filename)
                    print(f"   - {filename} ({file_size} bytes)")
            
            # Show preview of the plain YAML content
            if yaml_content:
                print(f"\nPreview of secret content:")
                print("-" * 40)
                lines = yaml_content.split('\n')
                for i, line in enumerate(lines[:15]):  # Show first 15 lines
                    print(line)
                if len(lines) > 15:
                    print(f"... ({len(lines) - 15} more lines)")
                    
        else:
            print("Secret created successfully!")
            if result.stdout:
                print(result.stdout)
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"Error executing kubectl command:")
        print(f"Return code: {e.returncode}")
        if e.stdout:
            print(f"STDOUT: {e.stdout}")
        if e.stderr:
            print(f"STDERR: {e.stderr}")
        return False
    except FileNotFoundError:
        print("Error: kubectl command not found. Please ensure kubectl is installed and in your PATH.")
        return False


def confirm_action(secret_name: str, namespace: str, key_value_pairs: Dict[str, str], use_sops: bool) -> str:
    """
    Show summary and ask for confirmation.
    
    Args:
        secret_name (str): Name of the secret
        namespace (str): Kubernetes namespace
        key_value_pairs (Dict[str, str]): Dictionary of key/value pairs
        use_sops (bool): Whether SOPS encryption will be used
    
    Returns:
        str: User choice ('1', '2', or '3')
    """
    print("\nSecret Summary:")
    print("-" * 20)
    print(f"Name: {secret_name}")
    print(f"Namespace: {namespace}")
    print(f"Keys: {', '.join(key_value_pairs.keys())}")
    print(f"Number of key/value pairs: {len(key_value_pairs)}")
    print(f"SOPS Encryption: {'Yes' if use_sops else 'No'}")
    
    if use_sops:
        print(f"Files to be created in dry-run:")
        print(f"  - {secret_name}-secret.yaml (plain)")
        print(f"  - {secret_name}-secret-sops.yaml (encrypted)")
    else:
        print(f"File to be created in dry-run:")
        print(f"  - {secret_name}-secret.yaml")
    
    dry_run_text = "Dry run (preview & save to YAML"
    if use_sops:
        dry_run_text += " with both plain and SOPS-encrypted versions"
    dry_run_text += ")"
    
    while True:
        choice = input(f"\nOptions:\n1. Create secret\n2. {dry_run_text}\n3. Cancel\nChoose (1/2/3): ").strip()
        if choice in ['1', '2', '3']:
            return choice
        print("Please enter 1, 2, or 3.")


def main():
    """Main function to orchestrate the secret creation process."""
    try:
        # Get user inputs
        secret_name, namespace, key_value_pairs, use_sops, age_key = get_user_inputs()
        
        # Show summary and get confirmation
        choice = confirm_action(secret_name, namespace, key_value_pairs, use_sops)
        
        if choice == '3':
            print("Operation cancelled.")
            return
        
        # Create kubectl command
        cmd = create_kubectl_command(secret_name, namespace, key_value_pairs)
        
        # Execute command
        dry_run = (choice == '2')
        success = run_kubectl_command(cmd, secret_name, use_sops, age_key, dry_run)
        
        if success and not dry_run:
            print(f"\n✅ Secret '{secret_name}' created successfully in namespace '{namespace}'!")
            print(f"\nTo view the secret:")
            print(f"kubectl get secret {secret_name} -n {namespace}")
            print(f"\nTo describe the secret:")
            print(f"kubectl describe secret {secret_name} -n {namespace}")
        elif success and dry_run:
            print(f"\n✅ Dry run completed successfully!")
            if use_sops:
                print(f"\n📖 Usage instructions:")
                print(f"Plain YAML:")
                print(f"  kubectl apply -f {secret_name}-secret.yaml")
                print(f"\nSOPS-encrypted YAML:")
                print(f"  # To view encrypted content:")
                print(f"  sops -d {secret_name}-secret-sops.yaml")
                print(f"  # To apply encrypted secret:")
                print(f"  sops -d {secret_name}-secret-sops.yaml | kubectl apply -f -")
            else:
                print(f"\n📖 Usage instructions:")
                print(f"kubectl apply -f {secret_name}-secret.yaml")
        else:
            print("\n❌ Failed to create secret.")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
