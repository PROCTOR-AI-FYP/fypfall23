import assert from 'node:assert/strict';
import test from 'node:test';
import {HeadPoseTracker,angles,rotationFromFaceMatrix} from '../src/lib/vision/head-pose.ts';
const radians=Math.PI/180;
function rotation(yaw=0,pitch=0,roll=0){
  const y=yaw*radians,p=-pitch*radians,z=roll*radians;
  const cy=Math.cos(y),sy=Math.sin(y),cp=Math.cos(p),sp=Math.sin(p),cz=Math.cos(z),sz=Math.sin(z);
  return [cz*cy,cz*sy*sp-sz*cp,cz*sy*cp+sz*sp,sz*cy,sz*sy*sp+cz*cp,sz*sy*cp-cz*sp,-sy,cy*sp,cy*cp];
}
function calibrate(tracker,r=rotation()) {tracker.calibrate();for(let i=0;i<=25;i++)tracker.update(r,i*.1,'',null,'640x360');return 2.5;}
test('MediaPipe column-major data preserves yaw/pitch/roll signs and removes scale',()=>{
  const r=rotation(35,-25,10),m=[r[0]*2,r[3]*2,r[6]*2,0,r[1]*2,r[4]*2,r[7]*2,0,r[2]*2,r[5]*2,r[8]*2,0,1,2,3,1];
  const pose=angles(rotationFromFaceMatrix(m));
  for(const [key,value]of Object.entries({yaw:35,pitch:-25,roll:10}))assert.ok(Math.abs(pose[key]-value)<1e-6,key);
});
test('non-forward posture and movement cannot establish neutral calibration',()=>{
  const tracker=new HeadPoseTracker();calibrate(tracker,rotation(55));assert.equal(tracker.neutral,null);
  tracker.calibrate();for(let i=0;i<40;i++)tracker.update(rotation(i%2?20:-20),5+i*.1);assert.equal(tracker.neutral,null);
});
test('a normal tilted exam posture becomes zero relative rotation',()=>{
  const tracker=new HeadPoseTracker();calibrate(tracker,rotation(12,-18,8));
  for(const key of ['yaw','pitch','roll'])assert.ok(Math.abs(tracker.status[key])<1e-6);
  assert.equal(tracker.status.state,'neutral');
});
for(const [label,r]of [['left',rotation(40)],['right',rotation(-40)],['down',rotation(0,-30)]])test(`${label} needs two continuous seconds and clears on return to centre`,()=>{
  const tracker=new HeadPoseTracker();const t=calibrate(tracker);
  for(let i=1;i<=12;i++)tracker.update(r,t+i*.1);assert.equal(tracker.status.sustained,false);
  for(let i=13;i<=35;i++)tracker.update(r,t+i*.1);assert.equal(tracker.status.sustained,true);
  for(let i=36;i<=45;i++)tracker.update(rotation(),t+i*.1);assert.equal(tracker.status.sustained,false);
});
test('missing faces and processing gaps cannot bridge the warning timer',()=>{
  const tracker=new HeadPoseTracker();const t=calibrate(tracker);
  for(let i=1;i<=15;i++)tracker.update(rotation(45),t+i*.1);
  tracker.update(null,4.1,'no_face');tracker.update(rotation(45),4.2);
  assert.equal(tracker.status.sustained,false);assert.ok(tracker.status.duration<.01);
  tracker.update(rotation(45),5);assert.equal(tracker.status.sustained,false);
});
test('multiple faces, long loss, camera changes and backward time revoke neutral',()=>{
  for(const update of [t=>t.update(null,2.6,'multiple_faces',null,'640x360'),t=>t.update(null,5,'no_face',null,'640x360'),t=>t.update(rotation(),2.6,'',null,'1280x720'),t=>t.update(rotation(),2,'',null,'640x360')]){
    const tracker=new HeadPoseTracker();calibrate(tracker);update(tracker);assert.equal(tracker.neutral,null);
  }
});
test('reflected, distorted and non-finite transforms are rejected',()=>{
  for(const matrix of [new Array(16).fill(NaN),[-1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],[2,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]])assert.throws(()=>rotationFromFaceMatrix(matrix));
});
