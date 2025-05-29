import os
import subprocess
import argparse
import sys
import re

def is_file_tracked_by_git(file_path, chromium_src_dir):
    """Checks if a file is tracked by the Git repository."""
    # Run git ls-files from within the chromium_src_dir
    command = [
        "git",
        "ls-files",
        "--error-unmatch", # Suppress errors for non-existent files
        file_path # This path is relative to chromium_src_dir
    ]
    try:
        # Use check=False to prevent CalledProcessError for untracked files
        subprocess.run(command, capture_output=True, text=True, check=False, cwd=chromium_src_dir)
        return True
    except subprocess.CalledProcessError:
        return False # File not tracked

def get_file_content(file_path):
    """Reads content of a file."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except FileNotFoundError:
        return None # File does not exist

def get_patch_new_file_content(patch_file_path):
    """Extracts the content of the new file from a 'new file' patch."""
    content_lines = []
    in_new_file_hunk = False
    with open(patch_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.startswith('--- /dev/null'): # This is a new file patch
                in_new_file_hunk = True
            elif in_new_file_hunk and line.startswith('+++ b/'):
                # Start of actual content lines after the header
                # Skip the "@@ ..." line
                next(f)
                break
        if in_new_file_hunk:
            for line in f:
                if line.startswith(('--- ', '+++ ', 'diff --git ')): # End of hunk/start of new patch
                    break
                if line.startswith('+'):
                    content_lines.append(line[1:]) # Strip the '+'
                elif not line.startswith('-'): # Include context lines for new file patches if any
                    content_lines.append(line)
    return ''.join(content_lines)

def apply_patch(patch_file_path, chromium_src_dir):
    """Applies a single patch file using git apply --reject."""
    patch_filename = os.path.basename(patch_file_path)
    print(f"  Processing patch: {patch_filename}...")

    # Extract target file path from patch header (e.g., from b/path/to/file)
    target_file_relative_path = None
    with open(patch_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.startswith('+++ b/'):
                # Strip the "b/" prefix and any trailing whitespace
                target_file_relative_path = line[len('+++ b/'):].strip()
                break
    if not target_file_relative_path:
        print(f"  ERROR: Could not determine target file from patch {patch_filename}. Skipping.", file=sys.stderr)
        return False, None # Return False for failure, None for status

    target_file_abs_path = os.path.join(chromium_src_dir, target_file_relative_path)

    command = [
        "git",
        "apply",
        # Removed -p1 and --git-dir/--work-tree.
        # git apply will infer these from the 'cwd' argument.
        "--verbose",
        "--reject",
        # Patch file path needs to be absolute, as cwd will change.
        patch_file_path,
    ]

    try:
        # CRITICAL CHANGE: Run the command from within the chromium_src_dir
        process = subprocess.run(command,
                                 cwd=chromium_src_dir,
                                 capture_output=True,
                                 text=True,
                                 check=False)

        if process.returncode == 0:
            print(f"  SUCCESS: {patch_filename} applied cleanly.")
            return True, "applied"
        else:
            stderr_output = process.stderr
            # Check for "already exists" error
            if "already exists in working directory" in stderr_output and target_file_relative_path:
                print(f"  INFO: {patch_filename}: Target file '{target_file_relative_path}' already exists.")
                # Is it a 'new file' patch?
                with open(patch_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    patch_content_lines = f.readlines()
                is_new_file_patch = patch_content_lines[0].startswith('--- /dev/null') if patch_content_lines else False

                if is_new_file_patch:
                    # For comparison, the tracked path is relative to chromium_src_dir
                    tracked_path_for_check = target_file_relative_path

                    if is_file_tracked_by_git(tracked_path_for_check, chromium_src_dir):
                        existing_content = get_file_content(target_file_abs_path)
                        patch_added_content = get_patch_new_file_content(patch_file_path)

                        # Simple content comparison (strip whitespace/newlines for robustness)
                        if existing_content and existing_content.strip() == patch_added_content.strip():
                            print(f"  SKIPPED: {patch_filename} (file already exists and content matches).")
                            return True, "skipped_identical"
                        else:
                            print(f"  FAILED: {patch_filename} (file already exists, but content differs).")
                            print("  Stderr:\n", stderr_output)
                            return False, "failed_content_mismatch"
                    else:
                        print(f"  FAILED: {patch_filename} (file '{target_file_relative_path}' exists but is untracked. Remove it first if intended to be created by patch).")
                        print("  Stderr:\n", stderr_output)
                        return False, "failed_untracked_exists"
                else: # It's an "already exists" error but not a new file patch - very unusual, treat as failure
                    print(f"  FAILED: {patch_filename} (unexpected 'already exists' for non-new-file patch).")
                    print("  Stderr:\n", stderr_output)
                    return False, "failed_unexpected_exists"
            else: # General failure (e.g., context mismatch)
                print(f"  FAILED: {patch_filename}.")
                print(f"  Return code: {process.returncode}")
                print("  Stderr:")
                print(stderr_output)
                print("  Stdout:")
                print(process.stdout)
                print(f"  Please check for .rej files in '{chromium_src_dir}'.")
                return False, "failed_conflict"

    except FileNotFoundError:
        print(f"ERROR: 'git' command not found. Ensure Git is installed and in your PATH.", file=sys.stderr)
        return False, None
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        return False, None

def main():
    parser = argparse.ArgumentParser(description="Apply Chromium patches for Cobalt.")
    parser.add_argument("--chromium-src-dir", required=True,
                        help="Path to the Chromium 'src' directory.")
    parser.add_argument("--patch-dir", required=True,
                        help="Path to the directory containing patch files.")

    args = parser.parse_args()

    # Resolve absolute paths
    chromium_src_dir_abs = os.path.abspath(args.chromium_src_dir)
    patch_dir_abs = os.path.abspath(args.patch_dir)

    # Basic validation
    if not os.path.isdir(chromium_src_dir_abs):
        print(f"Error: Chromium src directory not found: {chromium_src_dir_abs}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(os.path.join(chromium_src_dir_abs, ".git")):
        print(f"Error: .git directory not found in Chromium src. Is '{chromium_src_dir_abs}' a Git repository?", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(patch_dir_abs):
        print(f"Error: Patch directory not found: {patch_dir_abs}", file=sys.stderr)
        sys.exit(1)

    print(f"Chromium src directory: {chromium_src_dir_abs}")
    print(f"Patch directory:        {patch_dir_abs}")
    print("Patching mode:          Applying")
    print("-" * 40)

    patch_files = sorted([f for f in os.listdir(patch_dir_abs) if f.endswith(".patch")])

    if not patch_files:
        print(f"No .patch files found in {patch_dir_abs}. Exiting.")
        return

    successful_applied_count = 0
    successful_skipped_count = 0 # For patches skipped because file already exists and matches
    failed_count = 0
    failed_patches_list = []

    for i, patch_filename in enumerate(patch_files):
        patch_file_path = os.path.join(patch_dir_abs, patch_filename)
        print(f"[{i+1}/{len(patch_files)}]", end=" ")
        success, status = apply_patch(patch_file_path, chromium_src_dir_abs)
        if success:
            if status == "applied":
                successful_applied_count += 1
            elif status == "skipped_identical":
                successful_skipped_count += 1
        else:
            failed_count += 1
            failed_patches_list.append(f"{patch_filename} ({status})") # Append status for clarity

    print("-" * 40)
    print(f"Patching Summary:")
    print(f"  Total patches: {len(patch_files)}")
    print(f"  Successfully applied: {successful_applied_count}")
    print(f"  Skipped (already exists & content matches): {successful_skipped_count}")
    print(f"  Failed to apply: {failed_count}")

    if failed_count > 0:
        print("\nPlease resolve conflicts for the following patches:")
        for patch_info in failed_patches_list:
            print(f"- {patch_info}")
        print(f"Conflicts (if any) are saved as .rej files in '{chromium_src_dir_abs}'.")
        sys.exit(1)
    else:
        print("All patches applied successfully!")

if __name__ == "__main__":
    main()
