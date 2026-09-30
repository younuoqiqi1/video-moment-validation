import unittest,tempfile,json,subprocess,sys
from pathlib import Path
from unittest.mock import patch
try:
 from scripts import auto_review as m
except ImportError:
 import auto_review as m

class FollowupTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.config={'repository':'younuoqiqi1/video-moment-validation','prs':[3],'argv':['/fake/agy','--print','{prompt}']}
  self.pr={'number':3,'state':'open','draft':False,'title':'AGY：测试','head':{'sha':'a'*40,'ref':'feat/local-task-runner','repo':{'full_name':self.config['repository']}}}
 def tearDown(self):self.tmp.cleanup()
 def test_two_cycles_only_dispatch_once(self):
  with patch.object(m,'get_pr',return_value=self.pr),patch.object(m,'fetch_review',return_value='- 结论：request_changes\n修改任务'),patch.object(m,'make_worktree',return_value=self.root),patch.object(m,'run_agent',return_value=0) as run:
   m.once(self.root,self.config);m.once(self.root,self.config)
   self.assertEqual(run.call_count,1)
 def test_pass_does_not_start_agent(self):
  with patch.object(m,'get_pr',return_value=self.pr),patch.object(m,'fetch_review',return_value='结论：pass_with_notes'),patch.object(m,'run_agent') as run:
   m.once(self.root,self.config);run.assert_not_called()
 def test_closed_or_draft_not_dispatched(self):
  for field,value in [('state','closed'),('draft',True)]:
   pr={**self.pr,field:value}
   with patch.object(m,'get_pr',return_value=pr),patch.object(m,'fetch_review') as read:
    m.once(self.root,self.config);read.assert_not_called()
 def test_fetch_failure_not_dispatched(self):
  with patch.object(m,'get_pr',return_value=self.pr),patch.object(m,'fetch_review',side_effect=RuntimeError('offline')),patch.object(m,'run_agent') as run:
   with self.assertRaises(RuntimeError):m.once(self.root,self.config)
   run.assert_not_called()
 def test_negative_conclusion_not_pass(self):
  self.assertEqual(m.conclusion('结论：not_pass_with_notes'),'unknown')
 def test_unknown_pr_never_read(self):
  with patch.object(m,'get_pr') as read:m.once(self.root,{**self.config,'prs':[]});read.assert_not_called()
 def test_actual_git_does_not_reset_existing_branch(self):
  def git(*args):return subprocess.run(['git',*args],cwd=self.root,check=True,capture_output=True,text=True).stdout.strip()
  git('init','-b','main');git('config','user.name','test');git('config','user.email','test@example.invalid')
  (self.root/'sentinel').write_text('keep');git('add','.');git('commit','-m','base')
  git('checkout','-b','feat/local-task-runner');(self.root/'sentinel').write_text('extra');git('commit','-am','extra');before=git('rev-parse','HEAD');git('checkout','main')
  sha=git('rev-parse','HEAD');git('update-ref','refs/vmv-autoreview/pr-3',sha)
  path=m.make_worktree(self.root,3,sha)
  self.assertEqual(git('rev-parse','feat/local-task-runner'),before)
  self.assertEqual((self.root/'sentinel').read_text(),'keep')
  self.assertEqual(subprocess.run(['git','rev-parse','HEAD'],cwd=path,check=True,capture_output=True,text=True).stdout.strip(),sha)

if __name__=='__main__':unittest.main()
