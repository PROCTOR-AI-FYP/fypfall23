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

function plainPhone({offset=0,scale=1,angle=0,visible=true,left=48,surroundings=false}={}) {
  const width=320,height=180,data=new Uint8ClampedArray(width*height*4);
  const radians=angle*Math.PI/180,cos=Math.cos(radians),sin=Math.sin(radians),cx=left+18+offset,cy=63;
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const dx=x-cx,dy=y-cy,localX=(dx*cos+dy*sin)/scale,localY=(-dx*sin+dy*cos)/scale;
    const inside=Math.abs(localX)<18&&Math.abs(localY)<33;
    const context=Math.abs(localX)<26&&Math.abs(localY)<47;
    const background=surroundings&&context&&!inside?120+((x*19+y*7)%90):160;
    const value=visible&&inside?40:background;
    data.set([value,value,value,255],(y*width+x)*4);
  }
  return {width,height,data};
}

test('a plain phone uses visible contextual edges while preserving its original box',()=>{
  const tracker=new ObjectOverlayTracker();tracker.set([object],plainPhone(),0);
  assert.equal(tracker.patches.length,1);
  assert.equal(tracker.patches[0].contextual,true);
  const still=tracker.update(plainPhone(),100);
  assert.equal(still.length,1);
  still[0].box.forEach((value,i)=>assert.ok(Math.abs(value-object.box[i])<1e-9));
  const moved=tracker.update(plainPhone({offset:12}),200);
  assert.equal(moved.length,1);
  assert.equal(moved[0].track_id,object.track_id);
  assert.ok(Math.abs(moved[0].box[0]-60/320)<.01);
});

test('contextual matching never creates a track from a wholly uniform scene',()=>{
  const tracker=new ObjectOverlayTracker();tracker.set([object],plainPhone({visible:false}),0);
  assert.deepEqual(tracker.patches,[]);
  assert.deepEqual(tracker.update(plainPhone({visible:false}),100),[]);
});

test('unchanged contextual texture cannot retain a removed plain phone',()=>{
  const tracker=new ObjectOverlayTracker();tracker.set([object],plainPhone({surroundings:true}),0);
  assert.equal(tracker.update(plainPhone({surroundings:true}),100).length,1);
  assert.deepEqual(tracker.update(plainPhone({surroundings:true,visible:false}),200),[]);
});

test('plain phone tracking tolerates modest scale and rotation changes',()=>{
  const tracker=new ObjectOverlayTracker();tracker.set([object],plainPhone(),0);
  for(const [i,angle] of [12,24].entries()){
    const tracked=tracker.update(plainPhone({scale:1.12,angle,offset:6}),100+i*100);
    assert.equal(tracked.length,1);
    assert.ok(Math.abs((tracked[0].box[0]+tracked[0].box[2])/2-72/320)<.015);
    assert.ok(tracked[0].box[2]-tracked[0].box[0]>.11);
  }
});

test('delayed observations can recover a translated plain phone without stale boxes',()=>{
  const tracker=new ObjectOverlayTracker();tracker.set([object],plainPhone(),5000);
  const moved=tracker.update(plainPhone({offset:90}),5100);
  assert.equal(moved.length,1);
  assert.ok(Math.abs(moved[0].box[0]-138/320)<.015);
  assert.deepEqual(tracker.update(plainPhone({visible:false}),5200),[]);
});

test('contextual tracks preserve mapped-seat bounds and server observation expiry',()=>{
  const tracker=new ObjectOverlayTracker();tracker.set([object],plainPhone(),0,500);
  assert.deepEqual(tracker.update(plainPhone({offset:130}),100,[0,0,.48,1]),[]);
  assert.deepEqual(tracker.update(plainPhone(),501),[]);
  assert.deepEqual(tracker.patches,[]);
});

test('context clipped at the image edge does not shift the object box',()=>{
  const edgeObject={...object,box:[2/320,30/180,38/320,96/180]};
  const tracker=new ObjectOverlayTracker();tracker.set([edgeObject],plainPhone({left:2}),0);
  const tracked=tracker.update(plainPhone({left:2}),100);
  assert.equal(tracked.length,1);
  tracked[0].box.forEach((value,i)=>assert.ok(Math.abs(value-edgeObject.box[i])<1e-9));
});
