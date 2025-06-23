#!/usr/bin/env python3
"""
Quick test script to demonstrate tab completion functionality
"""

import os
import sys
import glob
from pathlib import Path

# Add the directory to Python path to import our completion functions
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False

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

def test_completion():
    """Test the tab completion functionality."""
    print("🚀 Tab Completion Test")
    print("=" * 50)
    
    if not HAS_READLINE:
        print("❌ readline module not available")
        print("📦 Install with: sudo apt-get install python3-readline")
        return
    
    print("✅ readline module available")
    
    if setup_path_completion():
        print("✅ Tab completion configured")
    else:
        print("❌ Failed to configure tab completion")
        return
    
    print("\n💡 Tab completion features:")
    print("   • Press TAB to complete directory/file names")
    print("   • Works with ~ (home directory)")
    print("   • Works with environment variables like $HOME")
    print("   • Directories get trailing / automatically")
    print("   • Case-insensitive completion")
    print("   • Shows all matches if ambiguous")
    
    print("\n📁 Try typing these and press TAB:")
    print("   ~/")
    print("   /home/")
    print("   /usr/loc")
    print("   $HOME/")
    
    print("\n" + "=" * 50)
    print("Enter a path (use TAB for completion, Ctrl+C to exit):")
    
    try:
        while True:
            path = input("Path: ")
            if path.strip():
                expanded = os.path.expanduser(os.path.expandvars(path))
                if os.path.exists(expanded):
                    if os.path.isdir(expanded):
                        print(f"✅ Directory exists: {expanded}")
                        # Show contents
                        try:
                            contents = os.listdir(expanded)[:5]  # First 5 items
                            print(f"   Contents (first 5): {contents}")
                        except PermissionError:
                            print("   (Permission denied to list contents)")
                    else:
                        print(f"✅ File exists: {expanded}")
                else:
                    print(f"❌ Path does not exist: {expanded}")
            else:
                print("Empty path entered")
                
    except (KeyboardInterrupt, EOFError):
        print("\n👋 Test completed!")

if __name__ == "__main__":
    test_completion()
