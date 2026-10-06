import test from 'node:test';
import assert from 'node:assert/strict';
import {reviewImage} from '../src/lib/evidence-media.ts';
const media=(overrides={})=>({clipStatus:'pending_upload',snapshotUrl:null,recordImageUrl:null,clip:null,...overrides});
test('a hosted snapshot remains available with the legacy pending clip status',()=>{
  assert.deepEqual(reviewImage(media({snapshotUrl:'https://signed.test/capture.jpg'})),{url:'https://signed.test/capture.jpg',kind:'snapshot'});
});
test('snapshot-only evidence uses the actual saved capture',()=>{
  assert.equal(reviewImage(media({clipStatus:'snapshot_only',snapshotUrl:'/api/detections/id/snapshot'})).url,'/api/detections/id/snapshot');
});
test('after video retention, the record image takes precedence over the trigger frame',()=>{
  assert.deepEqual(reviewImage(media({clipStatus:'deleted_after_review',recordImageUrl:'/record.jpg',snapshotUrl:'/snapshot.jpg'})),{url:'/record.jpg',kind:'record'});
});
test('a retained trigger image remains reviewable if no record image was stored',()=>{
  assert.equal(reviewImage(media({clipStatus:'deleted_after_review',snapshotUrl:'/snapshot.jpg'})).kind,'snapshot');
});
test('a saved record image is usable when snapshot delivery is absent',()=>{
  assert.equal(reviewImage(media({recordImageUrl:'/record.jpg'})).kind,'record');
});
test('missing or purged evidence cannot manufacture an image',()=>{
  assert.equal(reviewImage(media()),null);
});
