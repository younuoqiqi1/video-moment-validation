"""Scoped PR review follower; Python stdlib only. Does not merge or authorize stages."""
import argparse
import fcntl
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPOSITORY = 'younuoqiqi1/video-moment-validation'
LABEL = 'com.vmv.review-followup'

def git(root, *args):
    result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError('Git operation failed: ' + ' '.join(args[:2]))
    return result.stdout.strip()

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)

def get_pr(root, repository, number):
    # Credential output stays in memory and is never printed or persisted.
    cred = subprocess.run(['git', 'credential', 'fill'], cwd=root,
                          input='protocol=https\nhost=github.com\n\n',
                          capture_output=True, text=True, timeout=10,
                          env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    token = next((line[9:] for line in cred.stdout.splitlines() if line.startswith('password=')), None)
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'vmv-review-followup'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(f'https://api.github.com/repos/{repository}/pulls/{number}', headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)

def conclusion(text):
    match = re.search(r'^\s*(?:-\s*)?(?:\*\*)?(?:结论|conclusion)(?:\*\*)?\s*[:：]\s*`?([a-z_]+)', text, re.M|re.I)
    value = match.group(1).lower() if match else ''
    return value if value in {'pass', 'pass_with_notes', 'request_changes', 'blocked'} else 'unknown'

def fetch_review(root, number, sha):
    git(root, 'fetch', 'origin', '+refs/heads/main:refs/vmv-autoreview/main',
        f'+refs/pull/{number}/head:refs/vmv-autoreview/pr-{number}')
    if git(root, 'rev-parse', f'refs/vmv-autoreview/pr-{number}') != sha:
        raise RuntimeError('PR changed while fetching; retry next cycle')
    snapshot = git(root, 'rev-parse', 'refs/vmv-autoreview/main')
    result = subprocess.run(['git', 'show', f'{snapshot}:reviews/pr-{number}-{sha}.md'],
                            cwd=root, capture_output=True, text=True, timeout=10)
    return result.stdout if result.returncode == 0 else None

def make_worktree(root, number, sha):
    path = root / '.vmv-runner' / 'followup-worktrees' / f'pr-{number}-{sha}'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError('Existing followup directory requires inspection; preserving it')
    # A new private branch; never reset the user's PR branch or delete a directory.
    git(root, 'worktree', 'add', '-b', f'vmv-followup/pr-{number}-{sha}', str(path), sha)
    return path

def run_agent(argv, cwd, started):
    log = cwd.parent / (cwd.name + '.log')
    with log.open('a', encoding='utf-8') as output:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            started(proc.pid)
            return proc.wait(timeout=1800)
        except BaseException:
            # Prevent an untracked agent from continuing after persistence failure/timeout.
            import signal
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
            raise

def once(root, config):
    if config.get('repository') != REPOSITORY:
        raise RuntimeError('Repository outside authorized scope')
    state_path = root / '.vmv-runner' / 'review-followup-state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    # A crashed controller can leave an agent alive: stop for inspection, never retry blindly.
    if any(item.get('status') == 'running' for item in state.values()):
        raise RuntimeError('Previous agent requires inspection; no new agent started')
    for number in config['prs']:
        if number != 3:
            raise RuntimeError('Only current PR #3 repair is authorized')
        pr = get_pr(root, REPOSITORY, number)
        if pr.get('state') != 'open' or pr.get('draft') or not pr.get('title', '').startswith('AGY'):
            continue
        if pr['head']['repo']['full_name'] != REPOSITORY:
            raise RuntimeError('Unexpected PR repository')
        sha, branch = pr['head']['sha'], pr['head']['ref']
        if not re.fullmatch('[0-9a-f]{40}', sha):
            raise RuntimeError('Invalid head SHA')
        key = f'{number}:{sha}'
        if key in state:
            continue
        review = fetch_review(root, number, sha)
        if not review:
            continue
        decision = conclusion(review)
        if decision in {'pass', 'pass_with_notes'}:
            state[key] = {'status': 'review_passed'}
            save(state_path, state)
            continue
        if decision != 'request_changes':
            continue
        cwd = make_worktree(root, number, sha)
        # Recheck actual PR before dispatch: a newer push or closed PR cancels this attempt.
        current = get_pr(root, REPOSITORY, number)
        if current.get('state') != 'open' or current.get('draft') or current['head']['sha'] != sha:
            raise RuntimeError('PR changed before dispatch; preserving worktree')
        prompt = (f'仅修复已授权 PR #{number}，被审查提交 {sha}，目标远程分支 {branch}。'
                  '当前目录是独立工作区。按以下审查逐项修复并测试，更新阶段报告。'
                  f'完成后正常推送 HEAD 到 origin 的 {branch}，不要force，不另开PR。'
                  '推送冲突或环境阻塞时停止并记录具体原因。不合并、不认定用户验收、不进入下一阶段。'
                  '\n\n' + review)
        argv = [part.replace('{prompt}', prompt) for part in config['argv']]
        if sum(part.count('{prompt}') for part in config['argv']) != 1:
            raise RuntimeError('Exactly one prompt placeholder required')
        state[key] = {'status': 'running', 'worktree': str(cwd), 'branch': branch, 'pid': None}
        save(state_path, state)
        def started(pid):
            state[key]['pid'] = pid
            save(state_path, state)
        try:
            code = run_agent(argv, cwd, started)
            actual = get_pr(root, REPOSITORY, number)
            published = (code == 0 and actual.get('state') == 'open' and not actual.get('draft')
                         and actual['head']['ref'] == branch and actual['head']['sha'] != sha
                         and actual['head']['sha'] == git(cwd, 'rev-parse', 'HEAD'))
            state[key]['status'] = 'awaiting_review' if published else 'blocked'
            state[key]['exit_code'] = code
        except Exception as exc:
            state[key]['status'] = 'blocked'
            state[key]['error_type'] = type(exc).__name__
            raise
        finally:
            save(state_path, state)

def install(root, agy):
    git(root, 'rev-parse', '--show-toplevel')
    if subprocess.run(['git','check-ignore','-q','.vmv-runner/probe'],cwd=root).returncode:
        raise RuntimeError('Ignore .vmv-runner/ before installation')
    executable = shutil.which(agy) or (str(Path(agy).absolute()) if Path(agy).is_file() else None)
    if not executable:
        raise RuntimeError('Verified AGY executable missing')
    folder = root / '.vmv-runner'; folder.mkdir(exist_ok=True)
    stable = folder / 'auto_review.py';shutil.copy2(__file__,stable)
    save(folder/'review-followup-config.json', {'repository':REPOSITORY,'prs':[3],
         'argv':[executable,'--print','{prompt}','--model','gemini-3.8-flash-high','--dangerously-skip-permissions']})
    plist = Path.home()/'Library'/'LaunchAgents'/f'{LABEL}.plist';plist.parent.mkdir(parents=True,exist_ok=True)
    if plist.exists():
        raise RuntimeError('Service already configured; inspect before reinstalling')
    payload={'Label':LABEL,'ProgramArguments':[str(Path(sys.executable).absolute()),str(stable),'once','--repo',str(root)],
             'StartInterval':120,'RunAtLoad':True,'WorkingDirectory':str(root),
             'StandardOutPath':str(folder/'review-followup.log'),'StandardErrorPath':str(folder/'review-followup.log')}
    plist.write_bytes(plistlib.dumps(payload))
    proc=subprocess.run(['launchctl','load','-w',str(plist)],capture_output=True)
    if proc.returncode:raise RuntimeError('launchctl load failed; configuration preserved')
    print('Review follower installed: PR #3 only, every 120 seconds. Mac execution still needs verification.')

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['once','install','stop']);p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--agy',default=str(Path.home()/'.local/bin/agy'));args=p.parse_args();root=args.repo.resolve()
    if args.action=='install':install(root,args.agy);return
    if args.action=='stop':
        plist=Path.home()/'Library'/'LaunchAgents'/f'{LABEL}.plist'
        proc=subprocess.run(['launchctl','unload','-w',str(plist)],capture_output=True)
        if proc.returncode:raise RuntimeError('Unload failed; configuration preserved')
        plist.unlink();return
    folder=root/'.vmv-runner';folder.mkdir(exist_ok=True)
    # Share the existing runner lock so the two services cannot dispatch concurrently.
    with (folder/'runner.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        once(root,json.loads((folder/'review-followup-config.json').read_text()))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Review follower stopped:',type(exc).__name__,str(exc) if isinstance(exc,RuntimeError) else '')
        sys.exit(1)
