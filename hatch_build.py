"""Hatch build hook — stamps git hash into reasons_service/__init__.py."""

import subprocess

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        try:
            git_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.root,
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception:
            return

        init_path = self.root + "/reasons_service/__init__.py"
        with open(init_path) as f:
            content = f.read()
        if '__git_hash__ = ""' in content:
            with open(init_path, "w") as f:
                f.write(content.replace('__git_hash__ = ""', f'__git_hash__ = "{git_hash}"'))

    def finalize(self, version, build_data, artifact_path):
        init_path = self.root + "/reasons_service/__init__.py"
        with open(init_path) as f:
            content = f.read()
        import re
        restored = re.sub(r'__git_hash__ = "[^"]*"', '__git_hash__ = ""', content)
        if restored != content:
            with open(init_path, "w") as f:
                f.write(restored)
