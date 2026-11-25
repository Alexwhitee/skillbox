#!/usr/bin/env python3
"""Read-only, bounded project discovery; never imports or runs discovered code."""
import argparse
import json
from pathlib import Path

DEFAULT_ROOT = Path('/Users/xi/dev2/agent-skills')
SKIP = {'node_modules', 'vendor', 'dist', 'build', 'target', '__pycache__',
        'venv', 'env', 'site-packages', 'models', 'checkpoints', 'output', 'outputs'}
MARKERS = ('.git', 'package.json', 'pyproject.toml', 'requirements.txt',
           'Cargo.toml', 'go.mod', 'SKILL.md')


def inventory(roots, max_depth=3):
    if max_depth < 0:
        raise ValueError('max_depth must be nonnegative')
    projects, warnings, visited = [], [], set()

    def visit(directory, depth):
        if directory.is_symlink():
            return
        try:
            directory = directory.resolve()
            if directory in visited:
                return
            visited.add(directory)
            children = sorted(directory.iterdir(), key=lambda p: p.name.lower())
            names = {p.name for p in children}
            if any(marker in names for marker in MARKERS):
                entries = [p for p in children if p.is_file() and not p.is_symlink()
                           and (p.name in MARKERS or p.name in {'AGENTS.md', 'start.sh'}
                                or p.name.lower().startswith('readme'))]
                for pattern in ('skills/*/SKILL.md', 'plugin/skills/*/SKILL.md'):
                    entries.extend(p for p in directory.glob(pattern)
                                   if p.is_file() and not p.is_symlink())
                projects.append({'name': directory.name, 'path': str(directory),
                                 'git': '.git' in names,
                                 'entrypoints': sorted({str(p.relative_to(directory))
                                                        for p in entries})})
                return
            if depth < max_depth:
                for child in children:
                    if not child.name.startswith('.') and child.name not in SKIP:
                        if child.is_dir() and not child.is_symlink():
                            visit(child, depth + 1)
        except OSError as error:
            warnings.append(f'{directory}: {error.strerror or type(error).__name__}')

    for root in roots:
        root = Path(root).expanduser()
        if root.is_symlink():
            warnings.append(f'{root}: symlink root skipped')
        else:
            visit(root, 0)
    return {'roots': [str(Path(root).expanduser()) for root in roots],
            'max_depth': max_depth, 'projects': sorted(projects, key=lambda p: p['path']),
            'warnings': warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', action='append', help='Repeatable; replaces default root')
    parser.add_argument('--max-depth', type=int, default=3)
    args = parser.parse_args()
    if args.max_depth < 0:
        parser.error('--max-depth must be nonnegative')
    print(json.dumps(inventory(args.root or [DEFAULT_ROOT], args.max_depth),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
