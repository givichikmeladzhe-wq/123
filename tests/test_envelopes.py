import unittest

from runtime.envelopes import (
    AcceptanceCriterion, AckEnvelope, QAEnvelope, ResultEnvelope, TaskEnvelope,
    now_iso, validate_ack, validate_qa, validate_result, validate_task
)
from runtime.execution_enforcement import EnforcementError


class EnvelopeTests(unittest.TestCase):
    def task(self):
        return TaskEnvelope('1.0','TASK_ENVELOPE','t1','p1','c1','h1',1,'idem-1',now_iso(),'harmless schema validation',(
            AcceptanceCriterion('A1','schema valid'), AcceptanceCriterion('A2','no side effects')
        ))

    def ack(self,t):
        return AckEnvelope('1.0','ACK_ENVELOPE','t1','r1','c1','h2',2,1,t.digest,now_iso())

    def result(self,t,a):
        return ResultEnvelope('1.0','RESULT_ENVELOPE','t1','r1','c1','h2',3,1,t.digest,'SUCCEEDED',('artifact://result',),{'A1':True,'A2':True},now_iso())

    def qa(self,t,r):
        return QAEnvelope('1.0','QA_ENVELOPE','t1','r1','q1','c1','qa',4,1,t.digest,r.digest,'PASS',{'A1':True,'A2':True},('evidence://qa',),now_iso())

    def test_valid_chain(self):
        t=self.task(); a=self.ack(t); r=self.result(t,a); q=self.qa(t,r)
        validate_task(t); validate_ack(t,a); validate_result(t,a,r); validate_qa(t,a,r,q)

    def test_duplicate_criteria_rejected(self):
        t=TaskEnvelope('1.0','TASK_ENVELOPE','t1','p1','c1','h1',1,'idem',now_iso(),'x',(
            AcceptanceCriterion('A1','one'),AcceptanceCriterion('A1','two')
        ))
        with self.assertRaises(EnforcementError): validate_task(t)

    def test_stale_result_fencing_rejected(self):
        t=self.task(); a=self.ack(t); r=self.result(t,a)
        bad=ResultEnvelope(r.schema_version,r.message_type,r.task_id,r.run_id,r.correlation_id,r.sender_id,r.sequence,999,r.task_digest,r.status,r.artifact_refs,r.acceptance_results,r.completed_at)
        with self.assertRaises(EnforcementError): validate_result(t,a,bad)

    def test_self_qa_rejected(self):
        t=self.task(); a=self.ack(t); r=self.result(t,a); q=self.qa(t,r)
        bad=QAEnvelope(q.schema_version,q.message_type,q.task_id,q.run_id,q.qa_run_id,q.correlation_id,'h2',q.sequence,q.fencing_token,q.task_digest,q.result_digest,q.verdict,q.criterion_results,q.evidence_refs,q.completed_at)
        with self.assertRaises(EnforcementError): validate_qa(t,a,r,bad)

    def test_hash_tamper_rejected(self):
        t=self.task(); a=self.ack(t); r=self.result(t,a); q=self.qa(t,r)
        bad=QAEnvelope(q.schema_version,q.message_type,q.task_id,q.run_id,q.qa_run_id,q.correlation_id,q.sender_id,q.sequence,q.fencing_token,q.task_digest,'0'*64,q.verdict,q.criterion_results,q.evidence_refs,q.completed_at)
        with self.assertRaises(EnforcementError): validate_qa(t,a,r,bad)


if __name__=='__main__': unittest.main()
