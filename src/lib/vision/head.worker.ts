import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';
import { HeadPoseTracker, rotationFromFaceMatrix } from './head-pose';

const tracker=new HeadPoseTracker();
let model: FaceLandmarker | null=null;
let initialization: Promise<void> | null=null;
let mirrored=false, lastTimestamp=-1;
let reflected:OffscreenCanvas|null=null;
function detect(bitmap:ImageBitmap,timestamp:number,mirror:boolean) {
  let image:ImageBitmap|OffscreenCanvas=bitmap;
  if(mirror){
    if(!reflected||reflected.width!==bitmap.width||reflected.height!==bitmap.height)reflected=new OffscreenCanvas(bitmap.width,bitmap.height);
    const context=reflected.getContext('2d')!;
    context.setTransform(-1,0,0,1,bitmap.width,0);context.drawImage(bitmap,0,0);context.resetTransform();image=reflected;
  }
  lastTimestamp=Math.max(lastTimestamp+1,timestamp);
  return model!.detectForVideo(image,lastTimestamp);
}
async function init(origin: string) {
  const files=await FilesetResolver.forVisionTasks(`${origin}/vision/wasm`);
  model=await FaceLandmarker.createFromOptions(files, {
    baseOptions:{modelAssetPath:`${origin}/vision/face_landmarker.task`,delegate:'CPU'},
    runningMode:'VIDEO',numFaces:2,minFaceDetectionConfidence:.6,minFacePresenceConfidence:.6,
    minTrackingConfidence:.6,outputFacialTransformationMatrixes:true,
  });
  self.postMessage({type:'ready'});
}
self.onmessage=async (event: MessageEvent) => {
  const data=event.data;
  try {
    if (data.type==='init') { initialization=init(data.origin); await initialization; return; }
    if (data.type==='calibrate') { tracker.calibrate(); self.postMessage({type:'pose',status:tracker.status}); return; }
    if (data.type!=='frame') return;
    await initialization;
    const bitmap: ImageBitmap=data.bitmap;
    try {
      let result=detect(bitmap,data.timestamp,mirrored);
      if(!result.faceLandmarks.length){
        const recovered=detect(bitmap,data.timestamp,!mirrored);
        if(recovered.faceLandmarks.length){mirrored=!mirrored;result=recovered;}
      }
      let rotation: number[] | null=null, reason='no_face', box: number[] | null=null;
      if (result.faceLandmarks.length>1) reason='multiple_faces';
      else if (result.faceLandmarks.length===1) {
        const points=result.faceLandmarks[0].slice(0,468).map(point=>({...point,x:mirrored?1-point.x:point.x}));
        box=[Math.min(...points.map(p=>p.x)),Math.min(...points.map(p=>p.y)),Math.max(...points.map(p=>p.x)),Math.max(...points.map(p=>p.y))];
        if ((box[2]-box[0])*bitmap.width<60||(box[3]-box[1])*bitmap.height<70) reason='face_too_small';
        else if (box.some(v=>v<0||v>1)||!result.facialTransformationMatrixes.length) reason='unreliable_face';
        else {
          try{
            rotation=rotationFromFaceMatrix(result.facialTransformationMatrixes[0].data);
            // Reflect camera and canonical axes together, retaining the original
            // preview's proper rotation and its yaw/roll signs.
            if(mirrored)rotation=rotation.map((value,i)=>value*([0,3,6].includes(i)?-1:1)*(i<3?-1:1));
            reason='';
          }catch{reason='unreliable_face';}
        }
      }
      const status=tracker.update(rotation,data.timestamp/1000,reason,box,`${bitmap.width}x${bitmap.height}`);
      self.postMessage({type:'pose',status,timestamp:data.timestamp});
    } finally { bitmap.close(); }
  } catch (error) { self.postMessage({type:'error',message:(error as Error).message}); }
};
