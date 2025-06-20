#!/usr/bin/env python3
# validate_k8s_config.py
# A simple internal validation tool for Kubernetes configurations using Kustomize and Kubeconform.

import subprocess
import sys
import os
import tempfile
import yaml # For parsing kustomization.yaml
import shutil # For checking if commands exist
import platform # For more detailed OS info
import re # For parsing kubeconform output
import textwrap # For text wrapping

def run_command(command, error_message, capture_output=True):
    """
    Executes a shell command and checks for errors.
    Returns (stdout, stderr, returncode) on success.
    Exits the script on command not found or CalledProcessError.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=capture_output,
            text=True,
            check=True, # This will raise CalledProcessError on non-zero exit code
            shell=True
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.CalledProcessError as e:
        print(f"Error: {error_message}")
        print(f"Command failed with exit code {e.returncode}: {e.cmd}")
        print("\n--- Command Stdout ---")
        print(e.stdout.strip() if e.stdout else "No stdout")
        print("\n--- Command Stderr ---")
        print(e.stderr.strip() if e.stderr else "No stderr")
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: Command not found. Make sure '{command.split()[0]}' is installed and in your PATH.")
        sys.exit(1)

def install_tool(tool_name, os_info):
    """
    Attempts to install a missing tool based on OS.
    Returns True on success, False on failure.
    """
    print(f"\nAttempting to install {tool_name}...")
    try:
        if os_info['platform'] == 'linux':
            if os_info['distro'] == 'debian' or os_info['distro'] == 'ubuntu':
                if tool_name == "kustomize":
                    print("Using snap to install kustomize...")
                    subprocess.run(["sudo", "snap", "install", "kustomize", "--classic"], check=True)
                elif tool_name == "kubeconform":
                    print("Downloading and installing kubeconform manually...")
                    latest_kubeconform_version = "v0.6.1" # Manually set, consider automating fetching for production use
                    download_url = f"https://github.com/yannh/kubeconform/releases/download/{latest_kubeconform_version}/kubeconform-linux-amd64.tar.gz"
                    subprocess.run(["wget", download_url, "-O", "/tmp/kubeconform.tar.gz"], check=True)
                    subprocess.run(["tar", "-xzf", "/tmp/kubeconform.tar.gz", "-C", "/tmp/"], check=True)
                    subprocess.run(["sudo", "mv", "/tmp/kubeconform", "/usr/local/bin/"], check=True)
                    os.remove("/tmp/kubeconform.tar.gz")
            elif os_info['distro'] == 'fedora' or os_info['distro'] == 'centos' or os_info['distro'] == 'rhel':
                if tool_name == "kustomize":
                    print("Using dnf to install kustomize...")
                    subprocess.run(["sudo", "dnf", "install", "-y", "kustomize"], check=True)
                elif tool_name == "kubeconform":
                    print("Downloading and installing kubeconform manually...")
                    latest_kubeconform_version = "v0.6.1" # Manually set, consider automating fetching for production use
                    download_url = f"https://github.com/yannh/kubeconform/releases/download/{latest_kubeconform_version}/kubeconform-linux-amd64.tar.gz"
                    subprocess.run(["wget", download_url, "-O", "/tmp/kubeconform.tar.gz"], check=True)
                    subprocess.run(["tar", "-xzf", "/tmp/kubeconform.tar.gz", "-C", "/tmp/"], check=True)
                    subprocess.run(["sudo", "mv", "/tmp/kubeconform", "/usr/local/bin/"], check=True)
                    os.remove("/tmp/kubeconform.tar.gz")
            else:
                print(f"Automated installation for {tool_name} on your Linux distribution is not supported.")
                return False
        elif os_info['platform'] == 'darwin':
            if shutil.which("brew") is None:
                print("Homebrew is not installed. Please install Homebrew first: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
                return False
            if tool_name == "kustomize":
                subprocess.run(["brew", "install", "kustomize"], check=True)
            elif tool_name == "kubeconform":
                subprocess.run(["brew", "install", "kubeconform"], check=True)
        elif os_info['platform'] == 'win32':
            print("Automated installation on Windows is not implemented. Please install manually:")
            if tool_name == "kustomize":
                print("  - Chocolatey: choco install kustomize")
                print("  - Scoop: scoop install kustomize")
            elif tool_name == "kubeconform":
                print("  - Download manually from https://github.com/yannh/kubeconform/releases and add to PATH.")
            return False
        else:
            print(f"Automated installation for {tool_name} on your OS is not supported.")
            return False

        if shutil.which(tool_name) is not None:
            print(f"{tool_name} installed successfully.")
            return True
        else:
            print(f"Failed to verify {tool_name} installation.")
            return False

    except subprocess.CalledProcessError as e:
        print(f"Error during installation of {tool_name}:")
        print(f"Command '{' '.join(e.cmd)}' failed with exit code {e.returncode}")
        print(f"Stderr: {e.stderr.strip()}")
        print(f"Stdout: {e.stdout.strip()}")
        print("Please check the output and try installing manually if necessary.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during installation of {tool_name}: {e}")
        return False

def get_os_info():
    """Detects the operating system and distribution."""
    info = {'platform': sys.platform, 'distro': None}
    if sys.platform.startswith('linux'):
        try:
            release_info = platform.freedesktop_os_release()
            info['distro'] = release_info.get('ID', '').lower()
            if not info['distro']:
                if os.path.exists('/etc/debian_version'):
                    info['distro'] = 'debian'
                elif os.path.exists('/etc/redhat-release'):
                    info['distro'] = 'rhel'
                elif os.path.exists('/etc/fedora-release'):
                    info['distro'] = 'fedora'
        except Exception:
            if os.path.exists('/etc/debian_version'):
                info['distro'] = 'debian'
            elif os.path.exists('/etc/redhat-release'):
                info['distro'] = 'rhel'
            elif os.path.exists('/etc/fedora-release'):
                info['distro'] = 'fedora'
    return info

def check_and_install_tools():
    """
    Checks if kustomize and kubeconform are installed. If not, provides installation instructions
    and optionally installs them after user approval.
    """
    missing_tools = []
    
    if shutil.which("kustomize") is None:
        missing_tools.append("kustomize")
    
    if shutil.which("kubeconform") is None:
        missing_tools.append("kubeconform")

    if not missing_tools:
        return

    print("\n--- Missing Required Tools ---")
    print("The following tools are required but not found in your system's PATH:")
    for tool in missing_tools:
        print(f"- {tool}")
    
    install_option = input("Do you want to attempt to install the missing tools? (y/n): ").lower()

    if install_option == 'y':
        os_info = get_os_info()
        installed_successfully = True
        for tool in missing_tools:
            if not install_tool(tool, os_info):
                installed_successfully = False
                print(f"Could not install {tool}. Please install it manually.")
        
        if not installed_successfully:
            print("\n--- Installation Failed ---")
            print("Some tools could not be installed automatically. Please install them manually to proceed.")
            print("Refer to the instructions printed above or the official documentation:")
            print("- Kustomize: https://kustomize.io/docs/user/installation/")
            print("- Kubeconform: https://github.com/yannh/kubeconform/releases")
            sys.exit(1)
        else:
            print("\n--- All Missing Tools Installed (or verified) ---")
            if shutil.which("kustomize") is None or shutil.which("kubeconform") is None:
                print("Warning: Tools were installed but could not be verified in the current PATH.")
                print("Please try running the script again or verify your PATH setup.")
    else:
        print("\n--- Installation Declined ---")
        print("Required tools are missing and installation was declined. Exiting.")
        sys.exit(1)

def print_included_files_summary(included_files_summary, heading="--- Included Files Summary ---"):
    """Prints the formatted table of included files."""
    if included_files_summary:
        print(f"\n{heading}")
        print(f"{'Filename':<50} | Folder")
        print("-" * 70)
        included_files_summary.sort(key=lambda x: (x[1], x[0]))
        for f_name, folder in included_files_summary:
            print(f"{f_name:<50} | {folder}")
        print("-" * 70)
    else:
        print("\n--- No YAML files explicitly included via 'resources' or 'patches' in this Kustomization. ---")
        print("--- Please ensure your kustomization.yaml correctly lists its components. ---")


def validate_k8s_config(kustomize_path):
    """
    Main function to build Kustomize manifests and validate them with Kubeconform.
    """
    check_and_install_tools()

    if not kustomize_path:
        print("Usage: python validate_k8s_config.py <path-to-kustomization-directory>")
        print("Example: python validate_k8s_config.py clusters/staging")
        print("Example: python validate_k8s_config.py clusters/production")
        sys.exit(1)

    if not os.path.isdir(kustomize_path):
        print(f"Error: Kustomization directory '{kustomize_path}' not found.")
        sys.exit(1)

    print(f"--- Validating Kustomization: {kustomize_path} ---")

    kustomization_file_path = os.path.join(kustomize_path, "kustomization.yaml")
    if not os.path.exists(kustomization_file_path):
        print(f"Error: kustomization.yaml not found in '{kustomize_path}'.")
        sys.exit(1)

    included_files_summary = []

    try:
        with open(kustomization_file_path, 'r') as f:
            kustomization_data = yaml.safe_load(f)

        source_keys = ['resources', 'bases']
        for key in source_keys:
            if key in kustomization_data and kustomization_data[key]:
                for item_path in kustomization_data[key]:
                    full_item_path = os.path.abspath(os.path.join(kustomize_path, item_path))
                    if os.path.isdir(full_item_path):
                        for fname in os.listdir(full_item_path):
                            if fname.endswith(('.yaml', '.yml')):
                                included_files_summary.append((os.path.join(item_path, fname), os.path.basename(item_path)))
                    elif os.path.isfile(full_item_path) and item_path.endswith(('.yaml', '.yml')):
                        included_files_summary.append((item_path, os.path.basename(kustomize_path) + " (resource)"))

        if 'patches' in kustomization_data and kustomization_data['patches']:
            for patch_entry in kustomization_data['patches']:
                patch_file_rel_path = patch_entry.get('path')
                if patch_file_rel_path:
                    full_patch_path = os.path.abspath(os.path.join(kustomize_path, patch_file_rel_path))
                    if os.path.isfile(full_patch_path):
                        included_files_summary.append((patch_file_rel_path, os.path.basename(kustomize_path) + " (patch)"))
                    else:
                        print(f"Warning: Patch file '{full_patch_path}' specified in kustomization.yaml not found.")

        for fname in os.listdir(kustomize_path):
            if fname.endswith(('.yaml', '.yml')) and fname != "kustomization.yaml":
                relative_path = os.path.relpath(os.path.join(kustomize_path, fname), os.getcwd())
                if not any(item[0] == relative_path or item[0].endswith(fname) for item in included_files_summary):
                    included_files_summary.append((fname, os.path.basename(kustomize_path) + " (direct)"))

        print_included_files_summary(included_files_summary)

    except yaml.YAMLError as e:
        print(f"Error parsing kustomization.yaml in '{kustomize_path}': {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred while parsing Kustomization files for display: {e}")
        sys.exit(1)

    temp_fd, output_file_path = tempfile.mkstemp(suffix=".yaml", prefix="kubeconform-output-")

    try:
        os.close(temp_fd)

        print("\nBuilding Kustomize manifests...")
        stdout_kustomize, _, _ = run_command(
            f"kustomize build {kustomize_path}",
            f"Kustomize build failed for '{kustomize_path}'.",
            capture_output=True
        )
        with open(output_file_path, "w") as f:
            f.write(stdout_kustomize)
        print(f"Kustomize build successful. Output saved to {output_file_path}")

        # Build resource-to-file mapping for better error reporting
        print("\nBuilding resource-to-file mapping...")
        resource_to_file_map = {}
        
        def scan_yaml_files_for_resources(directory_path, relative_base_path=""):
            """Recursively scan YAML files and map resources to their file paths"""
            if not os.path.isdir(directory_path):
                return
                
            for item in os.listdir(directory_path):
                item_path = os.path.join(directory_path, item)
                relative_item_path = os.path.join(relative_base_path, item) if relative_base_path else item
                
                if os.path.isdir(item_path):
                    scan_yaml_files_for_resources(item_path, relative_item_path)
                elif item.endswith(('.yaml', '.yml')) and item != 'kustomization.yaml':
                    try:
                        with open(item_path, 'r') as f:
                            # Parse multiple YAML documents in a single file
                            for doc in yaml.safe_load_all(f):
                                if doc and isinstance(doc, dict):
                                    kind = doc.get('kind', '')
                                    metadata = doc.get('metadata', {})
                                    name = metadata.get('name', '')
                                    if kind and name:
                                        resource_key = f"{kind}/{name}"
                                        resource_to_file_map[resource_key] = f"./{os.path.join(relative_base_path, item)}"
                    except Exception as e:
                        # Skip files that can't be parsed
                        pass
        
        # Scan the base directory structure
        base_dir = os.path.dirname(kustomize_path)
        if base_dir:
            scan_yaml_files_for_resources(base_dir, os.path.basename(base_dir))
        
        # Also scan the current kustomization path
        scan_yaml_files_for_resources(kustomize_path, os.path.relpath(kustomize_path, '.'))

        print("\nValidating generated manifests with Kubeconform...")
        kubeconform_cmd = (
            f"kubeconform -strict -kubernetes-version 1.28.0 " # Specify your K8s version
            f"-schema-location default "
            f"-schema-location 'https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/' "
            f"-schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/' "
            f"-schema-location 'https://raw.githubusercontent.com/cert-manager/cert-manager/v1.12.0/deploy/crds/' " # Cert-Manager specific CRDs
            f"-schema-location 'https://raw.githubusercontent.com/traefik/traefik/v2.10/docs/schemas/providers/kubernetes_crd/' " # Traefik specific CRDs
            f"--skip Secret " # Added to skip Secret validation due to 'sops' field
            f"{output_file_path}"
        )

        kubeconform_result = subprocess.run(
            kubeconform_cmd,
            capture_output=True,
            text=True,
            shell=True,
            check=False
        )

        if kubeconform_result.returncode != 0:
            print("\n--- Kubeconform Validation FAILED ---")
            # Parse and format kubeconform output into table
            print("\n--- Kubeconform Validation Errors ---")
            stdout_lines = kubeconform_result.stdout.strip().splitlines() if kubeconform_result.stdout else []
            stderr_lines = kubeconform_result.stderr.strip().splitlines() if kubeconform_result.stderr else []
            all_error_lines = stdout_lines + stderr_lines
            
            if all_error_lines:
                # Table headers with full width columns - no truncation
                header_failed_resource = "Failed Resource"
                header_file_location = "File Location" 
                header_additional_info = "Additional Info"
                
                print(f"{header_failed_resource:<50} | {header_file_location:<70} | {header_additional_info}")
                print("-" * (50 + 3 + 70 + 3 + 120))
                
                # Parse each error line and extract information
                entry_count = 0
                for line in all_error_lines:
                    if line.strip() and not line.startswith("No stderr"):
                        # Add separator line between entries (except before the first entry)
                        if entry_count > 0:
                            separator_line = "-" * (50 + 3 + 70 + 3 + 80)
                            print(separator_line)
                        entry_count += 1
                        # Kubeconform output format: file_path - ResourceKind resource_name error_message
                        # Example: /tmp/file.yaml - PersistentVolumeClaim pvc-name is invalid: error details
                        
                        # Split on first " - " to separate file path from the rest
                        if " - " in line:
                            temp_file_path, rest = line.split(" - ", 1)
                            temp_file_path = temp_file_path.strip()
                            
                            # Extract resource kind and name, and error details
                            # Look for pattern: ResourceKind resource_name <rest_of_message>
                            resource_match = re.match(r"^(\S+)\s+(\S+)\s+(.+)$", rest.strip())
                            if resource_match:
                                resource_kind = resource_match.group(1)
                                resource_name = resource_match.group(2)
                                error_details = resource_match.group(3)
                                failed_resource = f"{resource_kind}/{resource_name}"
                                additional_info = error_details
                                
                                # Map to actual source file location
                                file_location = resource_to_file_map.get(failed_resource, "Source file not found")
                            else:
                                # If pattern doesn't match, use the whole rest as resource info
                                failed_resource = rest.strip()[:50] + "..." if len(rest.strip()) > 50 else rest.strip()
                                additional_info = "See full error details"
                                file_location = "Unknown source"
                        else:
                            # If no " - " separator found, treat whole line as error
                            file_location = "Unknown"
                            failed_resource = "Parse Error"
                            additional_info = line.strip()
                        
                        # Show full information with text wrapping for long additional info
                        failed_resource_display = failed_resource
                        file_location_display = file_location
                        
                        # Wrap long additional info text to multiple lines (80 chars per line)
                        wrapped_additional_info = textwrap.fill(additional_info, width=80).split('\n')
                        
                        # Print the first line with all columns
                        first_additional_info = wrapped_additional_info[0] if wrapped_additional_info else ""
                        print(f"{failed_resource_display:<50} | {file_location_display:<70} | {first_additional_info}")
                        
                        # Print continuation lines for additional info (if any)
                        for continuation_line in wrapped_additional_info[1:]:
                            print(f"{'':<50} | {'':<70} | {continuation_line}")
                
                print("-" * (35 + 3 + 45 + 3 + 100))
            else:
                print("No error details available.")
            
            print("\n--- Summary of Failing Resources (from Kubeconform) ---")
            header_resource = 'Kind/Name (from Kubeconform)'
            header_error_excerpt = 'Error Message (excerpt)'
            header_potential_files = 'Potential Source Files (from list above)'
            
            print(f"{header_resource:<40} | {header_error_excerpt:<60} | {header_potential_files}")
            print("-" * (40 + 3 + 60 + 3 + 70))

            failing_resource_details = []
            regex_kind_name = re.compile(r'^- (.+?)\s+-\s+([a-zA-Z0-9\-\.]+)/([a-zA-Z0-9\-\.]+)\s+-\s+(.+)$')
            regex_kind_only = re.compile(r'^- (.+?)\s+-\s+\((.+?)\)\s+-\s+(.+)$')

            error_lines = (kubeconform_result.stdout + kubeconform_result.stderr).splitlines()
            for line in error_lines:
                match_kind_name = regex_kind_name.match(line)
                if match_kind_name:
                    res_key = f"{match_kind_name.group(2)}/{match_kind_name.group(3)}"
                    error_msg_excerpt = match_kind_name.group(4).strip()
                    failing_resource_details.append((res_key, error_msg_excerpt)) # Removed included_files_summary here
                else:
                    match_kind_only = regex_kind_only.match(line)
                    if match_kind_only:
                        res_key = f"{match_kind_only.group(2)}/(unnamed)"
                        error_msg_excerpt = match_kind_only.group(3).strip()
                        failing_resource_details.append((res_key, error_msg_excerpt)) # Removed included_files_summary here

            if failing_resource_details:
                for res_key, error_msg_excerpt in sorted(failing_resource_details, key=lambda x: x[0]): # Iterate only on (res_key, error_msg_excerpt)
                    all_source_files_str = ", ".join([f"{f[0]} ({f[1]})" for f in included_files_summary])
                    displayed_sources = (all_source_files_str[:67] + '...') if len(all_source_files_str) > 67 else all_source_files_str
                    displayed_error_excerpt = (error_msg_excerpt[:57] + '...') if len(error_msg_excerpt) > 57 else error_msg_excerpt

                    print(f"{res_key:<40} | {displayed_error_excerpt:<60} | {displayed_sources}")

            else:
                 print(f"{'No specific resources identified':<40} | {'See Raw Kubeconform Output above':<60} | {'All source files listed above are potential causes.':<70}")

            print("-" * (40 + 3 + 60 + 3 + 70))

            print(f"\nDebugging Tip: The errors occurred in the consolidated YAML generated for '{kustomize_path}'.")
            print(f"You can inspect this full generated manifest at: {output_file_path}")
            print("To find the source of the error, look for the 'Kind/Name' reported by Kubeconform in the generated YAML, then check the relevant source files (from 'Included Files Summary' above) that define that resource. Look for typos in `kind`, `apiVersion`, incorrect field names, or invalid values according to Kubernetes schema.")
            sys.exit(1)
        else:
            print(f"Kubeconform validation successful for '{kustomize_path}'.")

    finally:
        if os.path.exists(output_file_path):
            os.remove(output_file_path)
            print(f"Cleaned up temporary file: {output_file_path}")

    print(f"\n--- Validation completed successfully for {kustomize_path} ---")
    sys.exit(0)

if __name__ == "__main__":
    kustomize_dir = sys.argv[1] if len(sys.argv) > 1 else ""
    validate_k8s_config(kustomize_dir)

