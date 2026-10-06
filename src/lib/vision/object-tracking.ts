// Appearance tracking is display-only; server observations create evidence.
export interface CameraObject {label:string;type:string;confidence:number;track_id:number|string;confirmed:boolean;box:number[]}
interface Sample {values:number[];norm:number;mean:number}
interface Candidate {x:number;y:number;scale:number;angle:number}
interface Patch extends Sample {
  object:CameraObject;width:number;height:number;center:number[];scale:number;angle:number;
  objectRegion:number[];contextual:boolean;contrast:number;interiorMean:number;expires:number;
}
const grid=8,minimumNorm=40,minimumMatch=.76;
const radians=(angle:number)=>angle*Math.PI/180;
function samples(gray:Uint8Array,width:number,height:number,x:number,y:number,w:number,h:number,angle=0):Sample|null {
  const values:number[]=[],cos=Math.cos(radians(angle)),sin=Math.sin(radians(angle));
  for(let row=0;row<grid;row++)for(let col=0;col<grid;col++) {
    const dx=w*((col+.5)/grid-.5),dy=h*((row+.5)/grid-.5);
    const px=Math.round(x+dx*cos-dy*sin),py=Math.round(y+dx*sin+dy*cos);
    if(px<0||py<0||px>=width||py>=height)return null;
    values.push(gray[py*width+px]);
  }
  const mean=values.reduce((a,b)=>a+b,0)/values.length,centered=values.map(v=>v-mean);
  return {values:centered,norm:Math.hypot(...centered),mean};
}
function grayscale(image:ImageData) {
  const gray=new Uint8Array(image.width*image.height);
  for(let i=0;i<gray.length;i++)gray[i]=(image.data[i*4]*77+image.data[i*4+1]*150+image.data[i*4+2]*29)>>8;
  return gray;
}
function objectBox(patch:Patch,candidate:Candidate,width:number,height:number) {
  const w=patch.width*width*candidate.scale,h=patch.height*height*candidate.scale;
  const cos=Math.cos(radians(candidate.angle)),sin=Math.sin(radians(candidate.angle));
  const [left,top,right,bottom]=patch.objectRegion,xs:number[]=[],ys:number[]=[];
  for(const x of [left,right])for(const y of [top,bottom]){
    const dx=(x-.5)*w,dy=(y-.5)*h;
    xs.push(candidate.x+dx*cos-dy*sin);ys.push(candidate.y+dx*sin+dy*cos);
  }
  return [Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];
}
const unique=(values:number[])=>Array.from(new Set(values));
const boundedScale=(value:number)=>Math.max(.55,Math.min(1.8,value));
const boundedAngle=(value:number)=>Math.max(-45,Math.min(45,value));
export class ObjectOverlayTracker {
  patches:Patch[]=[];
  set(objects:CameraObject[],image:ImageData,now:number,ttl=7000) {
    const gray=grayscale(image);
    this.patches=objects.flatMap(object=>{
      const box=object.box.map((v,i)=>v*(i%2?image.height:image.width));
      const [left,top,right,bottom]=box,w=right-left,h=bottom-top;
      if(box.some(v=>!Number.isFinite(v))||left<0||top<0||right>image.width||bottom>image.height||w<3||h<3)return [];
      const interior=samples(gray,image.width,image.height,(left+right)/2,(top+bottom)/2,w,h);
      if(!interior)return [];
      let context=box,sample=interior,contextual=false;
      // A plain phone screen often has no interior texture. Its visible border
      // and surroundings can provide a real match without inventing features.
      if(interior.norm<=minimumNorm){
        const padx=Math.max(3,w*.2),pady=Math.max(3,h*.2);
        context=[Math.max(0,left-padx),Math.max(0,top-pady),Math.min(image.width,right+padx),Math.min(image.height,bottom+pady)];
        const expanded=samples(gray,image.width,image.height,(context[0]+context[2])/2,(context[1]+context[3])/2,context[2]-context[0],context[3]-context[1]);
        if(!expanded||expanded.norm<=minimumNorm||Math.abs(interior.mean-expanded.mean)<12)return [];
        sample=expanded;contextual=true;
      }
      const cw=context[2]-context[0],ch=context[3]-context[1];
      return [{object,...sample,width:cw/image.width,height:ch/image.height,
        center:[(context[0]+context[2])/2/image.width,(context[1]+context[3])/2/image.height],scale:1,angle:0,
        objectRegion:[(left-context[0])/cw,(top-context[1])/ch,(right-context[0])/cw,(bottom-context[1])/ch],
        contextual,contrast:interior.mean-sample.mean,interiorMean:interior.mean,expires:now+ttl}];
    });
  }
  update(image:ImageData,now:number,bounds=[0,0,1,1]):CameraObject[] {
    const gray=grayscale(image),result:CameraObject[]=[];
    const [left,top,right,bottom]=bounds.map((v,i)=>v*(i%2?image.height:image.width));
    this.patches=this.patches.filter(patch=>now<=patch.expires);
    for(const patch of this.patches) {
      let best=minimumMatch,attempts=0;
      const found:{candidate:Candidate|null;box:number[]|null}={candidate:null,box:null};
      const previous:Candidate={x:patch.center[0]*image.width,y:patch.center[1]*image.height,scale:patch.scale,angle:patch.angle};
      const check=(candidate:Candidate)=>{
        // Keep worst-case work bounded when old observations require recovery.
        if(++attempts>4500)return;
        const box=objectBox(patch,candidate,image.width,image.height);
        if(box[0]<left||box[1]<top||box[2]>right||box[3]>bottom)return;
        const w=patch.width*image.width*candidate.scale,h=patch.height*image.height*candidate.scale;
        const sample=samples(gray,image.width,image.height,candidate.x,candidate.y,w,h,candidate.angle);
        if(!sample||sample.norm<=minimumNorm)return;
        if(patch.contextual){
          const [l,t,r,b]=patch.objectRegion,cos=Math.cos(radians(candidate.angle)),sin=Math.sin(radians(candidate.angle));
          const dx=((l+r)/2-.5)*w,dy=((t+b)/2-.5)*h;
          const interior=samples(gray,image.width,image.height,candidate.x+dx*cos-dy*sin,candidate.y+dx*sin+dy*cos,(r-l)*w,(b-t)*h,candidate.angle);
          // Matching unchanged surroundings alone must not retain a removed phone.
          const contrast=interior?interior.mean-sample.mean:0;
          if(!interior||contrast*patch.contrast<=0||Math.abs(contrast)<Math.abs(patch.contrast)*.45||Math.abs(interior.mean-patch.interiorMean)>35)return;
        }
        let dot=0;for(let i=0;i<grid*grid;i++)dot+=sample.values[i]*patch.values[i];
        const score=dot/(sample.norm*patch.norm);
        if(score>best){best=score;found.candidate=candidate;found.box=box;}
      };
      check(previous);
      if(best<.985){
        // Follow small movements/rotations locally before scanning the room.
        local:
        for(const scale of unique([patch.scale,boundedScale(patch.scale*.88),boundedScale(patch.scale*1.12)])){
          for(const angle of unique([patch.angle,boundedAngle(patch.angle-12),boundedAngle(patch.angle+12)])){
            for(let dy=-12;dy<=12;dy+=3)for(let dx=-12;dx<=12;dx+=3){
              check({...previous,x:previous.x+dx,y:previous.y+dy,scale,angle});
              if(best>.985)break local;
            }
          }
        }
      }
      if(best<.92){
        // Recovery handles an object translated while server inference was busy.
        const angles=unique([patch.angle,0,-15,15]);
        recovery:
        for(const scale of unique([patch.scale,boundedScale(patch.scale*.85),boundedScale(patch.scale*1.15)])){
          for(const angle of angles){
            const step=6;
            for(let y=top;y<=bottom&&attempts<4475;y+=step)for(let x=left;x<=right&&attempts<4475;x+=step){
              check({x,y,scale,angle});
              if(best>.985)break recovery;
            }
          }
        }
      }
      if(found.candidate&&found.box){
        // Refine the recovered location without lowering the match threshold.
        const coarse=found.candidate;
        for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++)check({...coarse,x:coarse.x+dx,y:coarse.y+dy});
        const selected=found.candidate;
        patch.center=[selected.x/image.width,selected.y/image.height];patch.scale=selected.scale;patch.angle=selected.angle;
        const box=found.box.map((v,i)=>v/(i%2?image.height:image.width));
        patch.object={...patch.object,box:box.map((v,i)=>Math.abs(v-patch.object.box[i])<1e-12?patch.object.box[i]:v)};
        result.push(patch.object);
      }
    }
    return result;
  }
}
