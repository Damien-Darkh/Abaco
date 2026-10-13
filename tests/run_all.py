import subprocess
import sys
from pathlib import Path


def main():
  # Determine the directory where this script is located (the 'tests' folder)
  script_dir = Path(__file__).resolve().parent

  print(f"Target Directory: {script_dir}")

  # Find all .py files in this same directory, excluding this script itself
  py_files = sorted(
      [
          f
          for f in script_dir.glob("*.py")
          if f.is_file() and f.resolve() != Path(__file__).resolve()
      ]
  )

  if not py_files:
    print("No other Python scripts found in this directory.")
    return

  print(f"Found {len(py_files)} script(s) to run.\n")

  # Run each script one after another
  for script in py_files:
    print("=" * 50)
    print(f"Starting: {script.name}")
    print("=" * 50)

    try:
      # Run the script using the current Python interpreter
      subprocess.run([sys.executable, str(script)], check=True)
      print(f"\n[SUCCESS] Finished {script.name}\n")
    except subprocess.CalledProcessError as e:
      print(
          f"\n[ERROR] Script {script.name} failed with exit code"
          f" {e.returncode}."
      )
      break
    except Exception as e:
      print(f"\n[ERROR] An unexpected error occurred while running {script.name}: {e}")
      break

  print("All tasks completed.")


if __name__ == "__main__":
  main()