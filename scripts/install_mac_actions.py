"""Install the official runner with the existing gh login; credentials stay local."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

REPO = 'younuoqiqi1/video-moment-validation'
RUNNER_DIR = Path.home() / '.local/share/vmv-actions-runner'


def select_archive(release, arch):
    arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64'}.get(arch)
    if not arch:
        raise ValueError('unsupported_arch')
    for asset in release['assets']:
        name = asset['name']
        if re.fullmatch(r'actions-runner-osx-' + arch + r'-[0-9.]+\.tar\.gz', name):
            url = asset['browser_download_url']
            if not url.startswith('https://github.com/actions/runner/releases/download/'):
                raise ValueError('untrusted_release_url')
            digest = asset.get('digest') or ''
            checksum = digest.removeprefix('sha256:')
            if not re.fullmatch(r'[a-f0-9]{64}', checksum):
                found = re.search(re.escape(name) + r'\s+([a-f0-9]{64})\b', release.get('body', ''))
                if not found:
                    raise ValueError('missing_checksum')
                checksum = found.group(1)
            return asset, checksum
    raise ValueError('missing_mac_archive')


def run(command, cwd=None):
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=300)
    if proc.returncode:
        raise RuntimeError('command_failed')
    return proc.stdout


def install(project):
    if platform.system() != 'Darwin':
        raise ValueError('not_macos')
    if not shutil.which('gh'):
        raise ValueError('missing_gh')
    run(['gh', 'auth', 'status'])
    project = project.resolve()
    if not (project / 'pyproject.toml').is_file():
        raise ValueError('invalid_project_root')
    RUNNER_DIR.mkdir(parents=True, exist_ok=True)
    runner_config = RUNNER_DIR / '.runner'
    if runner_config.exists():
        existing = json.loads(runner_config.read_text())
        if existing.get('gitHubUrl', '').rstrip('/') != f'https://github.com/{REPO}':
            raise ValueError('existing_runner_belongs_to_other_repo')
    else:
        # Refuse unknown partial installs; preserve their contents for diagnosis.
        if any(RUNNER_DIR.iterdir()):
            raise ValueError('runner_directory_not_empty')
        release = json.loads(run(['gh', 'api', 'repos/actions/runner/releases/latest']))
        asset, checksum = select_archive(release, platform.machine())
        with tempfile.TemporaryDirectory(prefix='vmv-runner-install-') as temp:
            run(['gh', 'release', 'download', release['tag_name'], '--repo', 'actions/runner',
                 '--pattern', asset['name'], '--dir', temp])
            archive = Path(temp) / asset['name']
            if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
                raise ValueError('checksum_mismatch')
            with tarfile.open(archive) as package:
                package.extractall(RUNNER_DIR, filter='data')
        registration = json.loads(run(['gh', 'api', '--method', 'POST', f'repos/{REPO}/actions/runners/registration-token']))
        run(['./config.sh', '--url', f'https://github.com/{REPO}', '--token', registration['token'],
             '--name', 'vmv-mac', '--labels', 'vmv-mac', '--work', '_work', '--unattended'], RUNNER_DIR)
    local = RUNNER_DIR / 'vmv-local.json'
    if not local.exists():
        python = project / '.venv/bin/python'
        local.write_text(json.dumps({'project_root': str(project), 'python': str(python)}, indent=2))
        local.chmod(0o600)
    if not (RUNNER_DIR / '.service').exists():
        run(['./svc.sh', 'install'], RUNNER_DIR)
    run(['./svc.sh', 'start'], RUNNER_DIR)
    runners = json.loads(run(['gh', 'api', f'repos/{REPO}/actions/runners']))['runners']
    configured = json.loads(runner_config.read_text())
    own = [r for r in runners if r['id'] == configured['agentId']]
    if not own or own[0]['status'] != 'online':
        print('服务已启动；GitHub 尚未确认在线。请稍后查 Runners 状态。')
        return 1
    print('GitHub 已确认 Mac 执行器在线；等待实际任务结果，不代表任务已完成。')
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        return install(args.project)
    except Exception as exc:
        safe = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'[a-z_]+', str(exc)) else 'installation_failed'
        print('安装阻塞：' + safe + '。未输出凭据或本机路径；请按安装说明检查。')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
