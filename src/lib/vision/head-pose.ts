// Same canonical-face rotation, signs and neutral-posture policy as the Python
// detector. MediaPipe JS exposes column-major matrices; our math is row-major.
export interface HeadState {
  state: string; calibrated: boolean; calibrating: boolean; calibration_progress: number;
  yaw: number | null; pitch: number | null; roll: number | null;
  violating: boolean; sustained: boolean; duration: number;
  box: number[] | null;
}
type Rotation = number[];
const degrees = 180 / Math.PI;
const dot = (a: number[], b: number[]) => a.reduce((sum, value, i) => sum + value * b[i], 0);
const cross = (a: number[], b: number[]) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const unit = (a: number[]) => { const length = Math.hypot(...a); if (length < 1e-6) throw Error('unreliable_face'); return a.map(v => v / length); };

export function orthogonal(matrix: Rotation): Rotation {
  if (matrix.length !== 9 || !matrix.every(Number.isFinite)) throw Error('unreliable_face');
  const a = [matrix[0],matrix[3],matrix[6]], b = [matrix[1],matrix[4],matrix[7]], c = [matrix[2],matrix[5],matrix[8]];
  const sizes = [a,b,c].map(v => Math.hypot(...v));
  if (Math.min(...sizes) < 1e-6 || Math.max(...sizes)/Math.min(...sizes)>1.2 || dot(cross(a,b),c)<=0) throw Error('unreliable_face');
  const x = unit(a), by = unit(b);
  if (Math.abs(dot(x,by))>.1) throw Error('unreliable_face');
  const y = unit(b.map((v,i) => v-dot(b,x)*x[i])), z = cross(x,y);
  return [x[0],y[0],z[0],x[1],y[1],z[1],x[2],y[2],z[2]];
}

export function rotationFromFaceMatrix(data: number[]): Rotation {
  if (data.length !== 16 || !data.every(Number.isFinite)) throw Error('unreliable_face');
  return orthogonal([data[0],data[4],data[8],data[1],data[5],data[9],data[2],data[6],data[10]]);
}

export function angles(r: Rotation) {
  const sy = Math.hypot(r[0],r[3]);
  if (sy<1e-5) throw Error('unreliable_face');
  return {yaw: Math.atan2(-r[6],sy)*degrees, pitch: -Math.atan2(r[7],r[8])*degrees, roll: Math.atan2(r[3],r[0])*degrees};
}
function relative(a: Rotation, b: Rotation) {
  return Array.from({length:9},(_,i) => [0,1,2].reduce((sum,k) => sum+a[k*3+Math.floor(i/3)]*b[k*3+i%3],0));
}
function distance(a: Rotation,b: Rotation) {
  const r=relative(a,b); return Math.acos(Math.max(-1,Math.min(1,(r[0]+r[4]+r[8]-1)/2)))*degrees;
}

export class HeadPoseTracker {
  private maxGap:number;
  private referenceLoss:number;
  constructor({maxGap=.5,referenceLoss=2}={}) {
    if(!Number.isFinite(maxGap)||maxGap<=0||!Number.isFinite(referenceLoss)||referenceLoss<maxGap)throw Error('Invalid head tracking timing');
    this.maxGap=maxGap;this.referenceLoss=referenceLoss;
  }
  neutral: Rotation | null = null;
  filtered: Rotation | null = null;
  samples: Rotation[] | null = null;
  calibrationStart: number | null = null;
  lastTime: number | null = null;
  lastValid: number | null = null;
  violationStart: number | null = null;
  shape = '';
  status: HeadState = {state:'calibration_required',calibrated:false,calibrating:false,calibration_progress:0,
    yaw:null,pitch:null,roll:null,violating:false,sustained:false,duration:0,box:null};

  calibrate() {
    this.neutral=this.filtered=null; this.samples=[]; this.calibrationStart=null;
    this.violationStart=null;
    this.status={...this.status,state:'calibrating',calibrated:false,calibrating:true,calibration_progress:0,yaw:null,pitch:null,roll:null,violating:false,sustained:false,duration:0};
  }
  update(rotation: Rotation | null, now: number, reason='no_face', box: number[] | null=null, shape=this.shape): HeadState {
    if (!Number.isFinite(now)) throw Error('Invalid timestamp');
    const dt=this.lastTime===null?null:now-this.lastTime;
    if (dt!==null&&(dt<=0||dt>this.maxGap)) { this.filtered=null; this.violationStart=null; this.resetSamples(); }
    if ((dt!==null&&(dt<=0||dt>=this.referenceLoss)) || (this.lastValid!==null&&now-this.lastValid>=this.referenceLoss) || (this.shape&&shape!==this.shape) || reason==='multiple_faces') this.neutral=null;
    this.lastTime=now; this.shape=shape;
    this.status={...this.status,box,calibrated:this.neutral!==null};
    if (!rotation) {
      this.filtered=null; this.violationStart=null; this.resetSamples();
      this.status={...this.status,state:reason,yaw:null,pitch:null,roll:null,violating:false,sustained:false,duration:0};
      return this.status;
    }
    this.lastValid=now;
    const raw=angles(rotation);
    if (this.samples!==null) {
      if (Math.abs(raw.yaw)>35||Math.abs(raw.pitch)>55||Math.abs(raw.roll)>35) {
        this.resetSamples(); this.status.state='face_forward_to_calibrate'; return this.status;
      }
      if (this.samples.length&&distance(this.samples[0],rotation)>5) this.resetSamples();
      if (!this.samples.length) this.calibrationStart=now;
      this.samples.push(rotation);
      const elapsed=now-this.calibrationStart!;
      this.status.state='calibrating'; this.status.calibration_progress=Math.min(1,elapsed/2,this.samples.length/8);
      if (elapsed<2||this.samples.length<8) return this.status;
      this.neutral=orthogonal(rotation.map((_,i) => this.samples!.reduce((sum,r) => sum+r[i],0)/this.samples!.length));
      this.samples=null; this.filtered=null; this.status.calibrating=false; this.status.calibrated=true;
    }
    if (!this.neutral) {
      this.filtered=null; this.violationStart=null;
      this.status={...this.status,state:'calibration_required',yaw:null,pitch:null,roll:null,violating:false,sustained:false,duration:0};
      return this.status;
    }
    const r=relative(this.neutral,rotation), alpha=dt===null?1:1-Math.exp(-Math.max(0,dt)/.12);
    this.filtered=this.filtered?orthogonal(r.map((v,i) => (1-alpha)*this.filtered![i]+alpha*v)):r;
    const pose=angles(this.filtered);
    if (Math.abs(pose.yaw)>80||Math.abs(pose.pitch)>75||Math.abs(pose.roll)>75) return this.update(null,now+.00001,'unreliable_face',box,shape);
    const enter=Math.abs(pose.yaw)>30||pose.pitch<-20;
    const remain=Math.abs(pose.yaw)>27||pose.pitch<-17;
    const violating=enter||(this.status.violating&&remain);
    if (!violating) this.violationStart=null;
    else this.violationStart??=now;
    const duration=this.violationStart===null?0:now-this.violationStart;
    const sustained=violating&&duration>=2;
    this.status={...this.status,...pose,violating,sustained,duration,state:sustained?'sustained':violating?'turning':'neutral'};
    return this.status;
  }
  private resetSamples() { if (this.samples!==null) { this.samples=[]; this.calibrationStart=null; this.status.calibration_progress=0; } }
}
