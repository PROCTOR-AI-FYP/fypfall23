import { HeadPoseTracker,type HeadState } from './head-pose.ts';

export interface RoomHeadRegion {seat_number:number;box:number[]}
export interface RoomHeadState extends HeadState {seat_number:number}
export class RoomHeadPoseTracker {
  private trackers=new Map<number,HeadPoseTracker>();
  private previousBoxes=new Map<number,number[]>();
  private regions:RoomHeadRegion[]=[];
  configure(regions:RoomHeadRegion[]){
    this.regions=regions.map(r=>({...r,box:[...r.box]}));this.trackers.clear();this.previousBoxes.clear();
    for(const r of regions)this.trackers.set(r.seat_number,new HeadPoseTracker({maxGap:2,referenceLoss:4}));
  }
  calibrate(){for(const tracker of this.trackers.values())tracker.calibrate();}
  observe(seat:number,rotation:number[]|null,now:number,reason:string,box:number[]|null,shape:string):RoomHeadState {
    const tracker=this.trackers.get(seat),region=this.regions.find(r=>r.seat_number===seat);
    if(!tracker||!region)throw Error('Unknown camera seat');
    if(box&&rotation){
      const area=(box[2]-box[0])*(box[3]-box[1]);
      const contained=Math.max(0,Math.min(box[2],region.box[2])-Math.max(box[0],region.box[0]))*Math.max(0,Math.min(box[3],region.box[3])-Math.max(box[1],region.box[1]));
      if(area<=0||contained/area<.85){rotation=null;reason='unreliable_face';}
      const previous=this.previousBoxes.get(seat);
      if(previous&&rotation){
        const overlap=Math.max(0,Math.min(box[2],previous[2])-Math.max(box[0],previous[0]))*Math.max(0,Math.min(box[3],previous[3])-Math.max(box[1],previous[1]));
        const priorArea=(previous[2]-previous[0])*(previous[3]-previous[1]);
        if(overlap/Math.max(area+priorArea-overlap,1e-9)<.15)tracker.neutral=null;
      }
      if(rotation)this.previousBoxes.set(seat,box);
    }else this.previousBoxes.delete(seat);
    return {seat_number:seat,...tracker.update(rotation,now,reason,box,shape)};
  }
}
