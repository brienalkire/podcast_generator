"""Compatibility wrapper for setups made before v0.3.0, such as a scheduled
task that runs `pythonw.exe generator.py` in this folder. New setups use the
`podcast-generator` command (or `python -m podcast_generator`) instead."""

from podcast_generator.generator import cli

if __name__ == "__main__":
    cli()
