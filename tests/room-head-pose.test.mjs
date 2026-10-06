import test from 'node:test';
import assert from 'node:assert/strict';
import {RoomHeadPoseTracker} from '../src/lib/vision/room-head-pose.ts';
const regions=[{seat_number:14,box:[0,0,.48,1]},{seat_number:25,box:[.52,0,1,1]}];
const box=seat=>seat===14?[.1,.2,.3,.5]:[.6,.2,.8,.5];
const rotation=(yaw=0)=>{const y=yaw*Math.PI/180;return [Math.cos(y),0,Math.sin(y),0,1,0,-Math.sin(y),0,Math.cos(y)];};
function calibrated(){const room=new RoomHeadPoseTracker();room.configure(regions);room.calibrate();
  for(let i=0;i<10;i++)for(const seat of [14,25])room.observe(seat,rotation(),i*.3,'',box(seat),'1280x720');return room;}
test('one camera calibrates both seats and only the turned student violates',()=>{
  const room=calibrated();let a,b;
  for(let i=10;i<24;i++){a=room.observe(14,rotation(),i*.3,'',box(14),'1280x720');b=room.observe(25,rotation(-42),i*.3,'',box(25),'1280x720');}
  assert.equal(a.calibrated,true);assert.equal(a.sustained,false);assert.equal(b.sustained,true);assert.ok(b.yaw< -30);
});
test('a missing face resets its warning without clearing another seat',()=>{
  const room=calibrated();for(let i=10;i<15;i++)room.observe(25,rotation(45),i*.3,'',box(25),'1280x720');
  assert.equal(room.observe(25,null,4.5,'no_face',null,'1280x720').sustained,false);
  assert.equal(room.observe(14,rotation(),4.5,'',box(14),'1280x720').calibrated,true);
  assert.equal(room.observe(25,rotation(45),4.6,'',box(25),'1280x720').sustained,false);
});
test('multiple faces revoke only their own neutral pose',()=>{
  const room=calibrated();assert.equal(room.observe(25,null,3,'multiple_faces',null,'1280x720').calibrated,false);
  assert.equal(room.observe(14,rotation(),3,'',box(14),'1280x720').calibrated,true);
});
test('a face outside its mapped seat cannot establish angles or a warning',()=>{
  const room=calibrated(),state=room.observe(14,rotation(45),3,'',box(25),'1280x720');
  assert.equal(state.state,'unreliable_face');assert.equal(state.yaw,null);assert.equal(state.sustained,false);
});
test('a new roster or camera resolution clears the independent neutral poses',()=>{
  const room=calibrated();assert.equal(room.observe(14,rotation(),3,'',box(14),'1600x900').calibrated,false);
  room.configure(regions);assert.equal(room.observe(25,rotation(),3,'',box(25),'1280x720').calibrated,false);
});
test('insufficient samples cannot show 100 percent calibration',()=>{
  const room=new RoomHeadPoseTracker();room.configure(regions);room.calibrate();let state;
  for(const now of [0,1,2])state=room.observe(14,rotation(),now,'',box(14),'1280x720');
  assert.equal(state.calibrated,false);assert.ok(state.calibration_progress<1);
});
