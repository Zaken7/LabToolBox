#!/usr/bin/env python3
"""
Image Promotion Tool for GitOps Workflows

This script compares image versions between staging kustomizations and base deployments,
allowing you to promote tested staging versions to production via base folder updates.

Usage:
    python3 promote_images.py [staging_path] [base_path]
    python3 promote_images.py --staging-path /path/to/staging --base-path /path/to/base
    
Environment Variables:
    STAGING_PATH or MY_STAGING_PATH - Path to staging apps directory
    BASE_PATH or MY_BASE_PATH - Path to base apps directory
"""

import os
import sys
import re
import yaml
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional

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


class ImageVersion:
    def __init__(self, name: str, tag: str):
        self.name = name
        self.tag = tag
    
    def __str__(self):
        return f"{self.name}:{self.tag}"


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


def get_directory_path(prompt_text: str) -> Path:
    """Get and validate directory path from user."""
    while True:
        dir_path = Prompt.ask(prompt_text)
        path = Path(dir_path).expanduser().resolve()
        if path.exists() and path.is_dir():
            return path
        console.print(f"❌ Directory {dir_path} does not exist or is not a directory!", style="red")


def resolve_path(path_str: str) -> Path:
    """Resolve path string, expanding environment variables and user home."""
    expanded = os.path.expandvars(os.path.expanduser(path_str))
    return Path(expanded).resolve()


def get_paths_from_args_or_env() -> Tuple[Optional[Path], Optional[Path]]:
    """Get staging and base paths from command line arguments or environment variables."""
    parser = argparse.ArgumentParser(
        description="GitOps Image Promotion Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/staging /path/to/base
  %(prog)s --staging-path /path/to/staging --base-path /path/to/base
  %(prog)s $MY_STAGING_PATH $MY_BASE_PATH
  
Environment Variables:
  STAGING_PATH or MY_STAGING_PATH - Path to staging apps directory
  BASE_PATH or MY_BASE_PATH - Path to base apps directory
        """
    )
    
    parser.add_argument(
        'staging_path', 
        nargs='?', 
        help='Path to staging apps directory'
    )
    parser.add_argument(
        'base_path', 
        nargs='?', 
        help='Path to base apps directory'
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
    
    args = parser.parse_args()
    
    # Determine staging path
    staging_path = None
    if args.staging_path:
        staging_path = resolve_path(args.staging_path)
    elif getattr(args, 'staging_path', None):
        staging_path = resolve_path(args.staging_path)
    else:
        # Try environment variables
        env_staging = os.getenv('STAGING_PATH') or os.getenv('MY_STAGING_PATH')
        if env_staging:
            staging_path = resolve_path(env_staging)
    
    # Determine base path
    base_path = None
    if args.base_path:
        base_path = resolve_path(args.base_path)
    elif getattr(args, 'base_path', None):
        base_path = resolve_path(args.base_path)
    else:
        # Try environment variables
        env_base = os.getenv('BASE_PATH') or os.getenv('MY_BASE_PATH')
        if env_base:
            base_path = resolve_path(env_base)
    
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
        # subtitle="Promote staging versions to production",
        style="bold blue"
    ))
    
    # Get paths from arguments, environment, or prompt user
    staging_path, base_path, dry_run = get_paths_from_args_or_env()
    
    # Validate staging path
    if staging_path:
        staging_path = validate_path(staging_path, "staging")
    
    if not staging_path:
        console.print("\n📁 First, let's locate your staging apps directory")
        console.print("   This should contain subdirectories with kustomization.yaml files")
        console.print("   Example: /path/to/flux/apps/staging")
        staging_path = get_directory_path("Enter the path to staging apps directory")
    
    # Validate base path
    if base_path:
        base_path = validate_path(base_path, "base")
    
    if not base_path:
        console.print("\n📁 Now, let's locate your base apps directory")
        console.print("   This should contain subdirectories with deployment.yaml files")
        console.print("   Example: /path/to/flux/apps/base")
        base_path = get_directory_path("Enter the path to base apps directory")
    
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
