"""Run every collected pytest item once across isolated local processes."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('target', nargs='?', default='tests/')
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('workers must be positive')
    pytest = [sys.executable, '-m', 'pytest', '-q', '-W', 'error']
    collection = subprocess.run([*pytest, '--collect-only', args.target], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if collection.returncode:
        print(collection.stdout, end='')
        return collection.returncode
    items = sorted(line for line in collection.stdout.splitlines() if '.py::' in line)
    summary = re.search(r'(?m)^(\d+) tests? collected\b', collection.stdout)
    if not summary or int(summary.group(1)) != len(items) or len(items) != len(set(items)):
        print('Unable to verify a complete, unique pytest collection.', file=sys.stderr)
        return 1
    groups = [items[i::args.workers] for i in range(args.workers)]
    groups = [group for group in groups if group]
    print(f'Running {len(items)} tests in {len(groups)} processes.', flush=True)
    with tempfile.TemporaryDirectory(prefix='wiki-pytest-') as temp:
        def run(index: int, group: list[str]) -> tuple[int, int, str]:
            log = Path(temp) / f'{index}.log'
            with log.open('w', encoding='utf-8') as output:
                result = subprocess.run([*pytest, *group], stdout=output, stderr=subprocess.STDOUT)
            return index, result.returncode, log.read_text(encoding='utf-8', errors='replace')
        failed = False
        with ThreadPoolExecutor(max_workers=len(groups)) as pool:
            futures = [pool.submit(run, index, group) for index, group in enumerate(groups)]
            for future in as_completed(futures):
                index, status, output = future.result()
                print(f'Process {index + 1}/{len(groups)}: {"passed" if status == 0 else "failed"}', flush=True)
                if status:
                    failed = True
                    print(output, end='', flush=True)
        return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
