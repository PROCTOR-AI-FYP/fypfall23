import assert from 'node:assert/strict';
import test from 'node:test';
import { ObjectOverlayTracker } from '../src/lib/vision/object-tracking.ts';

function frame(offset=0,visible=true) {
  const width=320,height=180,data=new Uint8ClampedArray(width*height*4);
  for(let i=0;i<width*height;i++)data.set([30,30,30,255],i*4);
  if(visible)for(let y=0;y<66;y++)for(let x=0;x<36;x++) {
    const value=80+((x*23+y*31+x*y*7)%170);
    data.set([value,value,value,255],((y+30)*width+x+48+offset)*4);
  }
  return {width,height,data};
}
const object={label:'phone',type:'PHONE_DETECTED',confidence:.91,track_id:7,confirmed:true,box:[48/320,30/180,84/320,96/180]};

test('stationary and moved objects keep display boxes between server observations',()=>{
  const tracker=new ObjectOverlayTracker();tracker.set([object],frame(),0);
  assert.deepEqual(tracker.update(frame(),100)[0],object);
  const moved=tracker.update(frame(12),200);
  assert.equal(moved.length,1);
  assert.equal(moved[0].track_id,7);
  assert.ok(Math.abs(moved[0].box[0]-60/320)<.02);
});
test('removed objects and expired observations cannot retain a display box',()=>{
  const tracker=new ObjectOverlayTracker();tracker.set([object],frame(),0);
  assert.deepEqual(tracker.update(frame(0,false),100),[]);
  assert.deepEqual(tracker.update(frame(),8000),[]);
});
test('room display tracking cannot move a box into another student region',()=>{
  const tracker=new ObjectOverlayTracker();tracker.set([object],frame(),0);
  assert.deepEqual(tracker.update(frame(130),200,[0,0,.48,1]),[]);
});
