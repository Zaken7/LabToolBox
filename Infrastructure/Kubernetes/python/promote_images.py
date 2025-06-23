#!/usr/bin/env python3
"""
Image Promotion Tool for GitOps Workflows

This script compares image versions between staging kustomizations and base deployments,
allowing you to promote tested staging versions to production via base folder updates.

Usage:
    python3 promote_images.py [staging_path] [base_path]
    python3 promote_images.py --staging-path /path/to/staging --base-path /path/to/base
    python3 promote_images.py $STAGING_PATH $BASE_PATH
    
Environment Variables:
    STAGING_PATH, MY_STAGING_PATH, APPS_STAGING_PATH - Path to staging apps directory
    BASE_PATH, MY_BASE_PATH, APPS_BASE_PATH - Path to base apps directory
    FLUX_APPS_DIR - Base directory containing both staging and base subdirectories
"""

import os
import sys
import re
import yaml
import argparse
import glob
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Import readline for tab completion
try:
    import readline
    import rlcompleter
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False

try:
    from rich.console import Console
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
except ImportError:
    print("❌ Rich module not found. Installing...")
    os.system("pip3 install rich")
    from rich.console import Console
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box

console = Console()


class PathCompleter:
    """Custom path completer for tab completion in prompts."""
    
    def __init__(self):
        self.matches = []
    
    def path_completer(self, text, state):
        """Generate path completions for the given text."""
        if state == 0:
            # First call - generate all matches
            self.matches = []
            
            # Expand user home and environment variables
            expanded_text = os.path.expanduser(os.path.expandvars(text))
            
            # If text ends with /, we're completing in a directory
            if expanded_text.endswith('/'):
                pattern = expanded_text + '*'
            else:
                # Otherwise, we're completing a partial path
                dirname = os.path.dirname(expanded_text)
                basename = os.path.basename(expanded_text)
                if dirname:
                    pattern = os.path.join(dirname, basename + '*')
                else:
                    pattern = basename + '*'
            
            try:
                # Get all matches
                potential_matches = glob.glob(pattern)
                
                for match in potential_matches:
                    # Convert back to the original format (with ~ if it was there)
                    if text.startswith('~'):
                        home = os.path.expanduser('~')
                        if match.startswith(home):
                            match = '~' + match[len(home):]
                    
                    # Add trailing slash for directories
                    if os.path.isdir(os.path.expanduser(os.path.expandvars(match))):
                        match += '/'
                    
                    self.matches.append(match)
                
                # Sort matches
                self.matches.sort()
                
            except (OSError, ValueError):
                # Handle cases where glob fails
                self.matches = []
        
        # Return the match for this state
        try:
            return self.matches[state]
        except IndexError:
            return None


class ImageVersion:
    def __init__(self, name: str, tag: str):
        self.name = name
        self.tag = tag
    
    def __str__(self):
        return f"{self.name}:{self.tag}"


def setup_path_completion():
    """Set up tab completion for paths."""
    if not HAS_READLINE:
        return False
    
    # Set up tab completion
    completer = PathCompleter()
    readline.set_completer(completer.path_completer)
    
    # Configure readline behavior
    readline.parse_and_bind("tab: complete")
    readline.parse_and_bind("set completion-ignore-case on")
    readline.parse_and_bind("set show-all-if-ambiguous on")
    readline.parse_and_bind("set mark-directories on")
    readline.parse_and_bind("set mark-symlinked-directories on")
    
    # Set characters that should trigger completion
    readline.set_completer_delims(' \t\n`!@#$%^&*()=+[{]}\\|;:\'",<>?')
    
    return True


def get_input_with_completion(prompt_text: str, default: str = None) -> str:
    """Get input with path completion enabled."""
    if HAS_READLINE:
        setup_path_completion()
        try:
            if default:
                # Pre-fill the input with default value
                def pre_input_hook():
                    readline.insert_text(default)
                    readline.redisplay()
                readline.set_pre_input_hook(pre_input_hook)
            
            result = input(f"{prompt_text}: ")
            
            # Clear the pre-input hook
            if default:
                readline.set_pre_input_hook(None)
            
            return result or default or ""
            
        except (EOFError, KeyboardInterrupt):
            raise
    else:
        # Fallback to regular input if readline not available
        if default:
            result = input(f"{prompt_text} [{default}]: ")
            return result or default
        else:
            return input(f"{prompt_text}: ")


def find_kustomization_files(apps_dir: Path) -> List[Path]:
    """Find all kustomization.yaml files in the apps directory."""
    kustomization_files = []
    for root, dirs, files in os.walk(apps_dir):
        for file in files:
            if file.lower() in ['kustomization.yaml', 'kustomization.yml']:
                kustomization_files.append(Path(root) / file)
    return kustomization_files


def extract_new_tags(kustomization_file: Path) -> List[ImageVersion]:
    """Extract newTag values from a kustomization file."""
    try:
        with open(kustomization_file, 'r') as f:
            content = yaml.safe_load(f)
        
        images = []
        if content and 'images' in content:
            for image_config in content['images']:
                if 'name' in image_config and 'newTag' in image_config:
                    images.append(ImageVersion(
                        name=image_config['name'],
                        tag=image_config['newTag']
                    ))
        
        return images
    except Exception as e:
        console.print(f"❌ Error reading {kustomization_file}: {e}", style="red")
        return []


def find_base_deployment_files(base_dir: Path, app_name: str) -> List[Path]:
    """Find deployment files in the base app directory."""
    app_base_dir = base_dir / app_name
    if not app_base_dir.exists():
        return []
    
    deployment_files = []
    for file in app_base_dir.glob("*.yaml"):
        if 'deployment' in file.name.lower() or 'statefulset' in file.name.lower():
            deployment_files.append(file)
    
    return deployment_files


def extract_base_images(deployment_file: Path) -> List[ImageVersion]:
    """Extract image versions from base deployment files."""
    try:
        with open(deployment_file, 'r') as f:
            content = f.read()
        
        # Regex to find image: lines
        image_pattern = r'image:\s*([^:\s]+):([^\s]+)'
        matches = re.findall(image_pattern, content)
        
        images = []
        for name, tag in matches:
            # Clean up any quotes
            name = name.strip('\'"')
            tag = tag.strip('\'"')
            images.append(ImageVersion(name=name, tag=tag))
        
        return images
    except Exception as e:
        console.print(f"❌ Error reading {deployment_file}: {e}", style="red")
        return []


def update_base_image(deployment_file: Path, old_image: ImageVersion, new_image: ImageVersion) -> bool:
    """Update image version in base deployment file."""
    try:
        with open(deployment_file, 'r') as f:
            content = f.read()
        
        # Replace the specific image line
        old_pattern = f"image:\\s*{re.escape(old_image.name)}:{re.escape(old_image.tag)}"
        new_line = f"image: {new_image.name}:{new_image.tag}"
        
        updated_content = re.sub(old_pattern, new_line, content)
        
        if updated_content != content:
            with open(deployment_file, 'w') as f:
                f.write(updated_content)
            return True
        
        return False
    except Exception as e:
        console.print(f"❌ Error updating {deployment_file}: {e}", style="red")
        return False


def get_env_variable_suggestions(var_type: str) -> List[str]:
    """Get list of environment variables that might contain the path."""
    if var_type == "staging":
        env_vars = ['STAGING_PATH', 'MY_STAGING_PATH', 'APPS_STAGING_PATH', 'FLUX_STAGING_PATH']
    else:  # base
        env_vars = ['BASE_PATH', 'MY_BASE_PATH', 'APPS_BASE_PATH', 'FLUX_BASE_PATH']
    
    # Add FLUX_APPS_DIR with subpath
    if var_type == "staging":
        env_vars.append('FLUX_APPS_DIR/staging')
    else:
        env_vars.append('FLUX_APPS_DIR/base')
    
    return env_vars


def show_env_suggestions(var_type: str) -> str:
    """Show environment variable suggestions and their current values."""
    env_vars = get_env_variable_suggestions(var_type)
    suggestions = []
    
    console.print(f"\n💡 You can set environment variables to avoid typing paths:")
    table = Table(title=f"Environment Variables for {var_type.title()} Path", box=box.SIMPLE)
    table.add_column("Variable", style="cyan")
    table.add_column("Current Value", style="dim")
    table.add_column("Usage Example", style="green")
    
    for var in env_vars:
        if '/' in var:
            # Handle FLUX_APPS_DIR/subdir case
            base_var, subdir = var.split('/', 1)
            current_value = os.getenv(base_var)
            if current_value:
                full_path = f"{current_value}/{subdir}"
                table.add_row(f"${base_var}/{subdir}", full_path, f"export {base_var}=/path/to/apps")
                suggestions.append(full_path)
            else:
                table.add_row(f"${base_var}/{subdir}", "[dim]Not set[/dim]", f"export {base_var}=/path/to/apps")
        else:
            current_value = os.getenv(var)
            if current_value:
                table.add_row(f"${var}", current_value, f"promote_images.py ${var} $BASE_PATH")
                suggestions.append(current_value)
            else:
                table.add_row(f"${var}", "[dim]Not set[/dim]", f"export {var}=/path/to/{var_type}")
    
    console.print(table)
    
    # Return the first valid suggestion found
    for suggestion in suggestions:
        if Path(suggestion).exists():
            return suggestion
    
    return None


def get_directory_path(prompt_text: str, var_type: str) -> Path:
    """Get and validate directory path from user with environment variable suggestions and tab completion."""
    # Show environment variable suggestions
    env_suggestion = show_env_suggestions(var_type)
    
    if env_suggestion and Path(env_suggestion).exists():
        use_env = Confirm.ask(f"\n✨ Use environment variable path: [cyan]{env_suggestion}[/cyan]?")
        if use_env:
            return Path(env_suggestion)
    
    console.print(f"\n📁 Enter the path to {var_type} apps directory:")
    if HAS_READLINE:
        console.print("   💡 Use TAB for path completion, arrow keys for history")
    console.print("   You can use environment variables like $STAGING_PATH, $HOME/flux/apps/staging, etc.")
    
    while True:
        try:
            dir_path = get_input_with_completion(
                prompt_text,
                default=env_suggestion if env_suggestion else None
            )
            
            if not dir_path.strip():
                if env_suggestion:
                    dir_path = env_suggestion
                else:
                    console.print("❌ Path cannot be empty!", style="red")
                    continue
            
            # Expand environment variables and user home
            expanded_path = os.path.expandvars(os.path.expanduser(dir_path))
            path = Path(expanded_path).resolve()
            
            if path.exists() and path.is_dir():
                return path
            
            console.print(f"❌ Directory {expanded_path} does not exist or is not a directory!", style="red")
            console.print("💡 Use TAB completion to browse existing directories")
            
        except (EOFError, KeyboardInterrupt):
            console.print("\n👋 Cancelled by user", style="yellow")
            sys.exit(0)


def resolve_path(path_str: str) -> Path:
    """Resolve path string, expanding environment variables and user home."""
    expanded = os.path.expandvars(os.path.expanduser(path_str))
    return Path(expanded).resolve()


def detect_flux_structure() -> Tuple[Optional[Path], Optional[Path]]:
    """Auto-detect common Flux/GitOps directory structures."""
    common_flux_paths = [
        "~/flux/apps",
        "~/gitops/apps", 
        "~/k8s/apps",
        "./apps",
        "../apps",
        "../../apps"
    ]
    
    flux_apps_dir = os.getenv('FLUX_APPS_DIR')
    if flux_apps_dir:
        common_flux_paths.insert(0, flux_apps_dir)
    
    for flux_path in common_flux_paths:
        expanded_path = Path(os.path.expanduser(flux_path))
        if expanded_path.exists():
            staging_path = expanded_path / "staging"
            base_path = expanded_path / "base"
            
            if staging_path.exists() and base_path.exists():
                console.print(f"🔍 Auto-detected Flux structure at: [cyan]{expanded_path}[/cyan]")
                return staging_path, base_path
    
    return None, None


def get_paths_from_args_or_env() -> Tuple[Optional[Path], Optional[Path], bool]:
    """Get staging and base paths from command line arguments or environment variables."""
    parser = argparse.ArgumentParser(
        description="GitOps Image Promotion Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/staging /path/to/base
  %(prog)s --staging-path /path/to/staging --base-path /path/to/base
  %(prog)s $STAGING_PATH $BASE_PATH
  %(prog)s $FLUX_APPS_DIR/staging $FLUX_APPS_DIR/base
  
Environment Variables:
  STAGING_PATH, MY_STAGING_PATH, APPS_STAGING_PATH - Path to staging apps directory
  BASE_PATH, MY_BASE_PATH, APPS_BASE_PATH - Path to base apps directory
  FLUX_APPS_DIR - Base directory containing both staging and base subdirectories
  
Set environment variables to avoid typing paths:
  export STAGING_PATH=/home/user/flux/apps/staging
  export BASE_PATH=/home/user/flux/apps/base
  # or
  export FLUX_APPS_DIR=/home/user/flux/apps

Tab Completion:
  Interactive prompts support TAB completion for paths (requires readline)
        """
    )
    
    parser.add_argument(
        'staging_path', 
        nargs='?', 
        help='Path to staging apps directory (supports env vars like $STAGING_PATH)'
    )
    parser.add_argument(
        'base_path', 
        nargs='?', 
        help='Path to base apps directory (supports env vars like $BASE_PATH)'
    )
    parser.add_argument(
        '--staging-path', 
        '-s',
        help='Path to staging apps directory (alternative to positional arg)'
    )
    parser.add_argument(
        '--base-path', 
        '-b',
        help='Path to base apps directory (alternative to positional arg)'
    )
    parser.add_argument(
        '--dry-run', 
        action='store_true',
        help='Show what would be promoted without making changes'
    )
    parser.add_argument(
        '--auto-detect',
        '-a',
        action='store_true',
        help='Auto-detect staging and base paths from common Flux structures'
    )
    
    args = parser.parse_args()
    
    # Auto-detect if requested
    if args.auto_detect:
        staging_path, base_path = detect_flux_structure()
        if staging_path and base_path:
            return staging_path, base_path, args.dry_run
    
    # Determine staging path (with environment variable expansion)
    staging_path = None
    if args.staging_path or args.staging_path:
        path_str = args.staging_path or args.staging_path
        staging_path = resolve_path(path_str)
    elif args.staging_path:
        staging_path = resolve_path(args.staging_path)
    else:
        # Try environment variables in order of preference
        for env_var in ['STAGING_PATH', 'MY_STAGING_PATH', 'APPS_STAGING_PATH', 'FLUX_STAGING_PATH']:
            env_value = os.getenv(env_var)
            if env_value:
                staging_path = resolve_path(env_value)
                break
        
        # Try FLUX_APPS_DIR/staging
        if not staging_path:
            flux_apps = os.getenv('FLUX_APPS_DIR')
            if flux_apps:
                potential_staging = resolve_path(f"{flux_apps}/staging")
                if potential_staging.exists():
                    staging_path = potential_staging
    
    # Determine base path (with environment variable expansion)
    base_path = None
    if args.base_path or args.base_path:
        path_str = args.base_path or args.base_path
        base_path = resolve_path(path_str)
    elif args.base_path:
        base_path = resolve_path(args.base_path)
    else:
        # Try environment variables in order of preference
        for env_var in ['BASE_PATH', 'MY_BASE_PATH', 'APPS_BASE_PATH', 'FLUX_BASE_PATH']:
            env_value = os.getenv(env_var)
            if env_value:
                base_path = resolve_path(env_value)
                break
        
        # Try FLUX_APPS_DIR/base
        if not base_path:
            flux_apps = os.getenv('FLUX_APPS_DIR')
            if flux_apps:
                potential_base = resolve_path(f"{flux_apps}/base")
                if potential_base.exists():
                    base_path = potential_base
    
    return staging_path, base_path, args.dry_run


def validate_path(path: Optional[Path], path_type: str) -> Path:
    """Validate that a path exists and is a directory."""
    if path is None:
        return None
    
    if not path.exists():
        console.print(f"❌ {path_type} directory {path} does not exist!", style="red")
        return None
    
    if not path.is_dir():
        console.print(f"❌ {path} is not a directory!", style="red")
        return None
    
    console.print(f"✅ Using {path_type} directory: [cyan]{path}[/cyan]")
    return path


def compare_and_promote_images():
    """Main function to compare and promote images."""
    console.print(Panel.fit(
        "🚀 GitOps Image Promotion Tool",
        subtitle="Promote staging versions to production • TAB completion enabled",
        style="bold blue"
    ))
    
    # Show readline status
    if HAS_READLINE:
        console.print("✅ Tab completion enabled for path input", style="green")
    else:
        console.print("⚠️  Tab completion not available (install readline)", style="yellow")
    
    # Try auto-detection first
    auto_staging, auto_base = detect_flux_structure()
    if auto_staging and auto_base:
        use_auto = Confirm.ask(f"🔍 Use auto-detected paths?\n   Staging: [cyan]{auto_staging}[/cyan]\n   Base: [cyan]{auto_base}[/cyan]")
        if use_auto:
            staging_path, base_path = auto_staging, auto_base
            dry_run = False
        else:
            # Get paths from arguments, environment, or prompt user
            staging_path, base_path, dry_run = get_paths_from_args_or_env()
    else:
        # Get paths from arguments, environment, or prompt user
        staging_path, base_path, dry_run = get_paths_from_args_or_env()
    
    # Validate staging path
    if staging_path:
        staging_path = validate_path(staging_path, "staging")
    
    if not staging_path:
        console.print("\n📁 Let's locate your staging apps directory")
        console.print("   This should contain subdirectories with kustomization.yaml files")
        console.print("   Example: /path/to/flux/apps/staging")
        staging_path = get_directory_path("Enter staging path", "staging")
    
    # Validate base path
    if base_path:
        base_path = validate_path(base_path, "base")
    
    if not base_path:
        console.print("\n📁 Now let's locate your base apps directory")
        console.print("   This should contain subdirectories with deployment.yaml files")
        console.print("   Example: /path/to/flux/apps/base")
        base_path = get_directory_path("Enter base path", "base")
    
    if dry_run:
        console.print("\n🔍 [yellow]DRY RUN MODE - No changes will be made[/yellow]")
    
    # Find all staging kustomization files
    console.print("\n🔍 Scanning staging kustomizations...")
    kustomization_files = find_kustomization_files(staging_path)
    
    if not kustomization_files:
        console.print("❌ No kustomization files found in staging directory!", style="red")
        return
    
    console.print(f"✅ Found {len(kustomization_files)} kustomization files")
    
    # Process each app
    promotions_available = []
    
    for kust_file in kustomization_files:
        app_name = kust_file.parent.name
        console.print(f"\n📦 Processing app: [bold cyan]{app_name}[/bold cyan]")
        
        # Extract staging image versions
        staging_images = extract_new_tags(kust_file)
        if not staging_images:
            console.print(f"  ℹ️  No image overrides found in {app_name}")
            continue
        
        # Find base deployment files
        base_deployment_files = find_base_deployment_files(base_path, app_name)
        if not base_deployment_files:
            console.print(f"  ❌ No base deployment files found for {app_name}", style="red")
            continue
        
        # Extract base image versions
        base_images = []
        for base_file in base_deployment_files:
            base_images.extend(extract_base_images(base_file))
        
        # Compare versions
        for staging_image in staging_images:
            matching_base = None
            base_file_with_image = None
            
            # Find matching base image
            for base_file in base_deployment_files:
                file_base_images = extract_base_images(base_file)
                for base_image in file_base_images:
                    if base_image.name == staging_image.name:
                        matching_base = base_image
                        base_file_with_image = base_file
                        break
                if matching_base:
                    break
            
            if matching_base:
                if matching_base.tag != staging_image.tag:
                    promotions_available.append({
                        'app': app_name,
                        'image_name': staging_image.name,
                        'current_tag': matching_base.tag,
                        'new_tag': staging_image.tag,
                        'base_file': base_file_with_image,
                        'staging_image': staging_image,
                        'base_image': matching_base
                    })
                    console.print(f"  🔄 Version difference found for {staging_image.name}")
                    console.print(f"     Base: [red]{matching_base.tag}[/red] → Staging: [green]{staging_image.tag}[/green]")
                else:
                    console.print(f"  ✅ {staging_image.name} versions match ({staging_image.tag})")
            else:
                console.print(f"  ⚠️  Image {staging_image.name} not found in base deployments", style="yellow")
    
    # Display promotion table
    if promotions_available:
        console.print(f"\n📊 [bold green]{len(promotions_available)}[/bold green] promotions available:")
        
        table = Table(title="Image Promotions Available", box=box.ROUNDED)
        table.add_column("App", style="cyan", no_wrap=True)
        table.add_column("Image", style="magenta")
        table.add_column("Current (Base)", style="red")
        table.add_column("New (Staging)", style="green")
        table.add_column("File", style="dim")
        
        for promo in promotions_available:
            table.add_row(
                promo['app'],
                promo['image_name'],
                promo['current_tag'],
                promo['new_tag'],
                promo['base_file'].name
            )
        
        console.print(table)
        
        if dry_run:
            console.print("\n🔍 [yellow]DRY RUN: These promotions would be available[/yellow]")
            return
        
        # Ask for promotions
        console.print("\n🚀 Ready to promote images:")
        
        for promo in promotions_available:
            promote_text = Text()
            promote_text.append(f"Promote ")
            promote_text.append(f"{promo['app']}/", style="cyan")
            promote_text.append(f"{promo['image_name']}", style="magenta")
            promote_text.append(f" from ")
            promote_text.append(f"{promo['current_tag']}", style="red")
            promote_text.append(f" to ")
            promote_text.append(f"{promo['new_tag']}", style="green")
            promote_text.append("?")
            
            if Confirm.ask(promote_text):
                success = update_base_image(
                    promo['base_file'],
                    promo['base_image'],
                    promo['staging_image']
                )
                
                if success:
                    console.print(f"  ✅ Successfully updated {promo['base_file']}", style="green")
                else:
                    console.print(f"  ❌ Failed to update {promo['base_file']}", style="red")
            else:
                console.print(f"  ⏭️  Skipped {promo['app']}/{promo['image_name']}")
        
        console.print("\n🎉 Promotion process complete!")
        console.print("💡 Don't forget to commit and push your changes to trigger production deployment!")
        
    else:
        console.print("\n✅ All image versions are already in sync!", style="green")
        console.print("💡 No promotions needed at this time.")


if __name__ == "__main__":
    try:
        compare_and_promote_images()
    except KeyboardInterrupt:
        console.print("\n\n👋 Promotion cancelled by user", style="yellow")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n❌ Unexpected error: {e}", style="red")
        sys.exit(1)
