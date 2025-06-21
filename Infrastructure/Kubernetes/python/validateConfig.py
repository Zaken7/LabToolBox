#!/usr/bin/env python3
# validate_k8s_config.py
#
# A validation tool for Kubernetes configurations that combines the output format
# of the original script with the modern enhancements of Rich tables and dependency management.
# Fixed version with proper text truncation handling and URL description fetching.

import argparse
import platform
import re
import subprocess
import sys
import urllib.request
import urllib.parse
from collections import defaultdict
from importlib import import_module
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory
from typing import List, Tuple, Dict, Optional

# --- Dependency Definitions ---
REQUIRED_PYTHON_PACKAGES = {"rich": "rich", "yaml": "PyYAML"}
REQUIRED_CLI_TOOLS = ["kustomize", "kubeconform"]

# --- Configuration ---
CRD_SCHEMA_LOCATIONS = [
    "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json",
    "https://raw.githubusercontent.com/cert-manager/cert-manager/v1.13.2/deploy/crds/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json",
    "https://raw.githubusercontent.com/argoproj/argo-cd/v2.9.3/manifests/crds/{{.ResourceKind}}.json",
    "https://raw.githubusercontent.com/fluxcd/source-controller/v1.2.3/config/crd/bases/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json",
    "https://raw.githubusercontent.com/traefik/traefik/v2.11/docs/content/reference/api/kubernetes-crd-definition-v1.yml",
]

# Global console object
console = None

# ==============================================================================
# URL Handling and Description Fetching
# ==============================================================================
def get_url_description(url: str, max_length: int = 80) -> str:
    """Fetch and return a description for a URL, or return a shortened version if too long."""
    if not url.startswith('http'):
        return url
    
    # If URL is not too long, return as is
    if len(url) <= max_length:
        return url
    
    try:
        # Try to fetch the page title or description
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status == 200:
                content = response.read().decode('utf-8', errors='ignore')
                # Look for title tag
                title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.IGNORECASE)
                if title_match:
                    title = title_match.group(1).strip()
                    if title and len(title) < max_length:
                        return f"{title} ({urllib.parse.urlparse(url).netloc})"
                
                # Look for description meta tag
                desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\'>]+)["\'][^>]*>', content, re.IGNORECASE)
                if desc_match:
                    desc = desc_match.group(1).strip()
                    if desc and len(desc) < max_length:
                        return f"{desc} ({urllib.parse.urlparse(url).netloc})"
    except Exception:
        # If fetching fails, fall back to shortened URL
        pass
    
    # Fallback: return shortened URL with domain
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc
    path_parts = parsed.path.split('/')
    
    if len(path_parts) > 2:
        shortened = f"{domain}/.../{'/'.join(path_parts[-2:])}"
    else:
        shortened = f"{domain}{parsed.path}"
    
    if len(shortened) > max_length:
        shortened = shortened[:max_length-3] + "..."
    
    return shortened

def get_kubeconform_url_description(url: str) -> str:
    """Specifically handle kubeconform URLs to extract meaningful descriptions."""
    if not url.startswith('http'):
        return url
    
    try:
        # Create a request with proper headers to avoid blocking
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; Kubeconform-Validator/1.0)'
        })
        
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status == 200:
                content = response.read().decode('utf-8', errors='ignore')
                
                # For GitHub URLs, try to extract meaningful info
                if 'github.com' in url:
                    # Look for repository description
                    repo_desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', content)
                    if repo_desc_match:
                        desc = repo_desc_match.group(1).strip()
                        if desc and desc != "GitHub":
                            return f"📖 {desc}"
                    
                    # Extract repository and file info from URL
                    url_parts = url.split('/') 
                    if len(url_parts) >= 5:
                        owner = url_parts[3]
                        repo = url_parts[4]
                        if 'crd' in url.lower() or 'schema' in url.lower():
                            return f"🔧 CRD Schema from {owner}/{repo}"
                        else:
                            return f"📁 Resource from {owner}/{repo}"
                
                # For other documentation URLs
                title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.IGNORECASE)
                if title_match:
                    title = title_match.group(1).strip()
                    # Clean up common title suffixes
                    title = re.sub(r's*[-|]s*(GitHub|Kubernetes|Documentation).*$', '', title)
                    if title and len(title) <= 80:
                        return f"📄 {title}"
                
                # Look for schema-specific descriptions
                if 'schema' in url.lower() or '.json' in url:
                    return "🔧 Kubernetes Resource Schema"
                
    except Exception as e:
        # If specific handling fails, provide context-aware fallback
        pass
    
    # Enhanced fallback based on URL patterns
    if 'crd' in url.lower():
        return "🔧 Custom Resource Definition Schema"
    elif 'schema' in url.lower():
        return "📋 Kubernetes Resource Schema"
    elif 'github.com' in url:
        # Extract owner/repo from GitHub URL
        url_parts = url.split('/') 
        if len(url_parts) >= 5:
            owner = url_parts[3]
            repo = url_parts[4]
            return f"📁 {owner}/{repo} (GitHub Repository)"
    elif 'kubernetes.io' in url:
        return "📖 Kubernetes Official Documentation"
    
    # Final fallback with domain
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc
    return f"🔗 {domain}"

def format_kubeconform_message(msg: str) -> str:
    """Format kubeconform error messages by replacing URLs with descriptions."""
    if not msg:
        return msg
    
    # Simple URL replacements
    replacements = [
        (r'https://raw\.githubusercontent\.com/yannh/kubernetes-json-schema/[^/]+/[^/]+/persistentvolumeclaim[^.\s]*\.json[^)\s]*', 
         '(📋 PersistentVolumeClaim Schema)'),
        (r'https://raw\.githubusercontent\.com/yannh/kubernetes-json-schema/[^/]+/[^/]+/[^.\s]*\.json[^)\s]*', 
         '(📋 Kubernetes Resource Schema)'),
        (r'https://raw\.githubusercontent\.com/[^/]+/[^/]+/[^/]+/[^/]+/crds/[^)\s]*', 
         '(🔧 Custom Resource Schema)'),
        (r'https://[^)\s]*github[^)\s]*schema[^)\s]*', 
         '(📋 Resource Schema)'),
    ]
    
    result = msg
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)
    
    # Clean up common error patterns
    if 'additionalProperties' in result and 'not allowed' in result:
        prop_match = re.search(r"additionalProperties '([^']+)' not allowed", result)
        if prop_match:
            prop = prop_match.group(1)
            result = f"Property '{prop}' is not allowed in this resource type"
    
    return result

def format_display_text(text: str, max_length: int = 80) -> str:
    """Format text for display, handling long URLs appropriately."""
    if not text:
        return text
    
    # Check if text contains URLs
    url_pattern = r'https?://[^\s]+'
    urls = re.findall(url_pattern, text)
    
    formatted_text = text
    for url in urls:
        if len(url) > max_length:
            description = get_url_description(url, max_length)
            formatted_text = formatted_text.replace(url, description)
    
    return formatted_text

# ==============================================================================
# Dependency Checking and Installation Logic
# ==============================================================================
def check_and_install_dependencies():
    global console
    pre_check_print = print
    if import_module_silently("rich"):
        from rich.console import Console
        console = Console(stderr=True)
        pre_check_print = console.print

    missing_py = [pkg for name, pkg in REQUIRED_PYTHON_PACKAGES.items() if not import_module_silently(name)]
    missing_cli = [tool for tool in REQUIRED_CLI_TOOLS if not which(tool)]
    if not missing_py and not missing_cli: return

    pre_check_print("\n--- [bold yellow]Missing Dependencies Detected[/bold yellow] ---")
    if missing_py: pre_check_print("Required Python packages: " + ", ".join(f"[cyan]{p}[/cyan]" for p in missing_py))
    if missing_cli: pre_check_print("Required CLI tools: " + ", ".join(f"[cyan]{t}[/cyan]" for t in missing_cli))

    try: answer = input("\nDo you want to attempt to install them? (y/n): ").lower()
    except (EOFError, KeyboardInterrupt): sys.exit(1)
    if answer != 'y': sys.exit(1)
    
    pre_check_print("\n--- [bold]Attempting Installation[/bold] ---")
    all_success = True
    for pkg in missing_py:
        if not _install_python_package(pkg, pre_check_print): all_success = False
    for tool in missing_cli:
        if not _install_cli_tool(tool, pre_check_print): all_success = False
    if not all_success: sys.exit(1)
    if missing_py:
        pre_check_print("\n[bold green]Dependencies installed.[/bold green] Please run the script again.")
        sys.exit(0)

def import_module_silently(name):
    try: import_module(name); return True
    except ImportError: return False

def _install_python_package(pkg, printer):
    printer(f"  -> Installing Python package: [bold cyan]{pkg}[/bold cyan]...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=True, capture_output=True, text=True)
        printer(f"  [green]✓ Successfully installed {pkg}.[/green]"); return True
    except subprocess.CalledProcessError as e:
        printer(f"  [bold red]✗ Error installing {pkg}:[/bold red]\n  Stderr: {e.stderr.strip()}"); return False

def _install_cli_tool(tool, printer):
    printer(f"  -> Installing CLI tool: [bold cyan]{tool}[/bold cyan]...")
    if sys.platform == "darwin" and which("brew"): cmd = ["brew", "install", tool]
    elif sys.platform.startswith("linux"):
        sudo = ["sudo"] if which("sudo") else []
        if Path("/etc/debian_version").exists(): cmd = sudo + ["apt-get", "install", "-y", tool]
        elif Path("/etc/redhat-release").exists(): cmd = sudo + ["dnf", "install", "-y", tool]
        else: return False
    else: return False
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        printer(f"  [green]✓ Successfully installed {tool}.[/green]"); return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        printer(f"  [bold red]✗ Error installing {tool}: {e}[/bold red]"); return False

# ==============================================================================
# Kustomize Parsing and Resource Mapping Logic
# ==============================================================================
def build_resource_map(base_path: Path) -> Dict[str, str]:
    import yaml
    resource_map = {}
    for yaml_file in base_path.rglob("*.yaml"):
        if yaml_file.name == "kustomization.yaml": continue
        try:
            for doc in yaml.safe_load_all(yaml_file.read_text()):
                if doc and isinstance(doc, dict):
                    kind, name = doc.get("kind"), doc.get("metadata", {}).get("name")
                    if kind and name:
                        resource_map[f"{kind}/{name}"] = str(yaml_file)
        except (yaml.YAMLError, IOError):
            pass
    return resource_map

def print_included_files_summary(kustomize_path: Path):
    from rich.table import Table
    from rich import box
    console.print(f"\n[bold]--- Included Files Summary ---[/bold]")
    table = Table(box=box.MINIMAL, show_header=True, header_style="bold cyan")
    table.add_column("Filename", style="green", no_wrap=False)
    table.add_column("Folder", style="yellow", no_wrap=False)
    
    files_by_folder = defaultdict(list)
    for f in kustomize_path.rglob("*.yaml"):
        relative_path = f.relative_to(kustomize_path)
        folder = relative_path.parts[0] if len(relative_path.parts) > 1 else "."
        files_by_folder[folder].append(str(relative_path))

    last_folder = None
    for folder in sorted(files_by_folder.keys()):
        if folder == ".": continue
        if last_folder is not None:
            table.add_section()
        for file_path in sorted(files_by_folder[folder]):
            table.add_row(file_path, folder)
        last_folder = folder

    console.print(table)

# ==============================================================================
# Main Application and Output Logic
# ==============================================================================
def run_command(command: List[str]) -> Tuple[str, str, int]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        console.print(f"Error: Command not found. Make sure '[bold]{command[0]}[/bold]' is installed.")
        sys.exit(1)

def build_kustomize(kustomize_path: Path) -> Optional[str]:
    console.print("\n[bold]Building Kustomize manifests...[/bold]")
    stdout, stderr, returncode = run_command(["kustomize", "build", str(kustomize_path)])
    
    if returncode != 0 or not stdout.strip():
        console.print("\n[bold red]✗ Kustomize Build FAILED[/bold red]")
        if not stdout.strip(): console.print("Error: 'kustomize build' produced no output.")
        if stderr.strip(): console.print(f"[red]Stderr:\n{stderr}[/red]")
        return None
        
    console.print("[green]✓ Kustomize build successful.[/green]")
    return stdout

def validate_with_kubeconform(content: str, k8s_ver: str, skip: List[str], file_path: Path) -> Tuple[str, str, int]:
    console.print("\n[bold]Validating generated manifests with Kubeconform...[/bold]")
    file_path.write_text(content)
    cmd = ["kubeconform", "-strict", f"-kubernetes-version={k8s_ver}"] + [f"-skip={k}" for k in skip] + ["-schema-location=default"] + [f"-schema-location={loc}" for loc in CRD_SCHEMA_LOCATIONS] + [str(file_path)]
    return run_command(cmd)

def print_validation_errors(stdout: str, stderr: str, resource_map: Dict[str, str]):
    from rich.table import Table
    from rich import box
    console.print("\n[bold red]✗ Kubeconform Validation FAILED[/bold red]")
    console.print("\n[bold]--- Kubeconform Validation Errors ---[/bold]")
    
    table = Table(box=box.MINIMAL, show_header=True, header_style="bold magenta")
    table.add_column("Failed Resource", style="cyan", no_wrap=False)
    table.add_column("File Location", style="green", no_wrap=False)
    table.add_column("Additional Info", style="yellow", no_wrap=False)

    all_lines = (stdout.strip() + "\n" + stderr.strip()).strip().splitlines()
    parsed_errors = []

    for line in all_lines:
        if " - " not in line: continue
        parts = line.split(" - ", 1)
        rest = parts[1]
        kind, name, msg = ("Unknown", "Unknown", rest)
        match = re.match(r"(\S+)\s+(\S+)\s+(.+)", rest)
        if match:
            kind, name, msg = match.groups()
        
        key = f"{kind}/{name}"
        location = resource_map.get(key, "[dim]Generated by Kustomize?[/dim]")
        # Format the message to handle long URLs
        formatted_msg = format_kubeconform_message(msg.strip())
        parsed_errors.append({"key": key, "location": location, "msg": formatted_msg})

    for i, error in enumerate(parsed_errors):
        table.add_row(error["key"], error["location"], error["msg"])
        if i < len(parsed_errors) - 1:
             table.add_section()

    if parsed_errors:
        console.print(table)
    else:
        console.print("\n[yellow]Could not parse specific errors. Raw output below:[/yellow]")
        if stdout.strip(): console.print("\n--- [bold]Stdout[/bold] ---\n" + f"[dim]{stdout.strip()}[/dim]")
        if stderr.strip(): console.print("\n--- [bold]Stderr[/bold] ---\n" + f"[red]{stderr.strip()}[/red]")
        
    return parsed_errors

def print_summary_of_failing_resources(parsed_errors):
    from rich.table import Table
    from rich import box
    console.print("\n[bold]--- Summary of Failing Resources (from Kubeconform) ---[/bold]")
    table = Table(box=box.MINIMAL, show_header=True, header_style="bold cyan")
    table.add_column("Kind/Name (from Kubeconform)", style="green", no_wrap=False)
    table.add_column("Error Message (excerpt)", style="yellow", no_wrap=False)
    table.add_column("Potential Source Files", style="green", no_wrap=False)

    if not parsed_errors:
        table.add_row("No specific resources identified", "See Raw Kubeconform Output above", "All source files listed above are potential causes.")
    else:
        for error in parsed_errors:
            # Format error message and location for display
            formatted_msg = format_display_text(error['msg'])
            formatted_location = format_display_text(error['location'])
            table.add_row(error['key'], formatted_msg, formatted_location)

    console.print(table)

def main():
    check_and_install_dependencies()

    parser = argparse.ArgumentParser(description="A validation tool for Kubernetes configurations.")
    parser.add_argument("kustomize_path", type=Path, help="Path to the directory containing a kustomization.yaml file.")
    parser.add_argument("--k8s-version", default="1.28.0", help="Target Kubernetes version.")
    parser.add_argument("--skip", action="append", default=["Secret"], help="Resource Kinds to skip.")
    args = parser.parse_args()

    kustomize_path = args.kustomize_path.resolve()
    if not kustomize_path.is_dir() or not (kustomize_path / "kustomization.yaml").exists():
        console.print(f"Error: Path '[bold red]{kustomize_path}[/bold red]' is not a valid Kustomization directory.")
        sys.exit(1)

    console.print(f"--- Validating Kustomization: [bold cyan]{kustomize_path}[/bold cyan] ---")
    print_included_files_summary(kustomize_path)

    console.print("\n[bold]Building resource-to-file mapping...[/bold]")
    resource_map = build_resource_map(kustomize_path)
    console.print("[green]✓ Resource map created.[/green]")

    kustomize_output = build_kustomize(kustomize_path)
    if kustomize_output is None: sys.exit(1)

    with TemporaryDirectory() as tmpdir_name:
        manifest_file = Path(tmpdir_name) / "manifest.yaml"
        stdout, stderr, returncode = validate_with_kubeconform(kustomize_output, args.k8s_version, args.skip, manifest_file)

        if returncode == 0:
            console.print("[green]✓ Kubeconform validation successful.[/green]")
            console.print(f"\n[bold green]Validation completed successfully for {kustomize_path}[/bold green]")
            sys.exit(0)
        else:
            parsed_errors = print_validation_errors(stdout, stderr, resource_map)
            print_summary_of_failing_resources(parsed_errors)
            console.print("\n[bold]Debugging Tip:[/bold]")
            console.print(f"You can inspect the fully rendered manifest at: [dim]{manifest_file}[/dim]")
            sys.exit(1)

if __name__ == "__main__":
    main()
