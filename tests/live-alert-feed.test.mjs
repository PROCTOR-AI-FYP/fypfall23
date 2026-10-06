import test from 'node:test';
import assert from 'node:assert/strict';
import {LiveAlertFeed} from '../src/lib/live-alert-feed.ts';
const event=(id,seconds=0,status='New',sessionId='exam')=>({id,sessionId,detectedAt:new Date(2026,0,1,0,0,seconds).toISOString(),status,studentId:id,seatNumber:seconds});
test('a snapshot begun before a camera alert cannot remove it',()=>{
  const feed=new LiveAlertFeed('exam'),snapshot=feed.beginSnapshot();feed.receive(event('phone',1));feed.reconcile(snapshot,[]);
  assert.deepEqual(feed.list().map(e=>e.id),['phone']);
});
test('out-of-order REST responses cannot replace a newer reviewed snapshot',()=>{
  const feed=new LiveAlertFeed('exam'),old=feed.beginSnapshot(),fresh=feed.beginSnapshot();
  feed.reconcile(fresh,[event('head',0,'Reviewed')]);assert.equal(feed.reconcile(old,[]),false);assert.equal(feed.list()[0].status,'Reviewed');
});
test('socket and HTTP delivery of the same detection produce one alert',()=>{
  const feed=new LiveAlertFeed('exam');feed.receive(event('phone',2));feed.receive(event('phone',2));
  assert.equal(feed.list().length,1);feed.reconcile(feed.beginSnapshot(),[event('phone',2,'Confirmed')]);
  feed.receive(event('phone',2));assert.equal(feed.list()[0].status,'Confirmed');
});
test('simultaneous students remain separate, newest first, and other exams stay out',()=>{
  const feed=new LiveAlertFeed('exam');feed.receive(event('studentA',1));feed.receive(event('studentB',2));
  assert.equal(feed.receive(event('foreign',3,'New','elsewhere')),false);assert.deepEqual(feed.list().map(e=>e.id),['studentB','studentA']);
});
test('authoritative REST dismissal updates the feed after a missed socket event',()=>{
  const feed=new LiveAlertFeed('exam');feed.receive(event('phone'));feed.reconcile(feed.beginSnapshot(),[event('phone',0,'Dismissed')]);
  assert.equal(feed.list()[0].status,'Dismissed');
});
