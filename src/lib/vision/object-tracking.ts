// Appearance tracking is display-only; server observations create evidence.
export interface CameraObject {label:string;type:string;confidence:number;track_id:number;confirmed:boolean;box:number[]}
interface Patch {object:CameraObject;values:number[];norm:number;width:number;height:number;expires:number}
const grid=8;
function samples(gray:Uint8Array,width:number,height:number,box:number[]) {
  const [x,y,right,bottom]=box,values:number[]=[];
  for(let row=0;row<grid;row++)for(let col=0;col<grid;col++) {
    const px=Math.round(x+(right-x)*(col+.5)/grid),py=Math.round(y+(bottom-y)*(row+.5)/grid);
    if(px<0||py<0||px>=width||py>=height)return null;
    values.push(gray[py*width+px]);
  }
  const mean=values.reduce((a,b)=>a+b,0)/values.length,centered=values.map(v=>v-mean),norm=Math.hypot(...centered);
  return norm>40?{values:centered,norm}:null;
}
function grayscale(image:ImageData) {
  const gray=new Uint8Array(image.width*image.height);
  for(let i=0;i<gray.length;i++)gray[i]=(image.data[i*4]*77+image.data[i*4+1]*150+image.data[i*4+2]*29)>>8;
  return gray;
}
export class ObjectOverlayTracker {
  patches:Patch[]=[];
  set(objects:CameraObject[],image:ImageData,now:number,ttl=7000) {
    const gray=grayscale(image);
    this.patches=objects.flatMap(object=>{
      const box=object.box.map((v,i)=>v*(i%2?image.height:image.width)),sample=samples(gray,image.width,image.height,box);
      return sample?[{object,...sample,width:box[2]-box[0],height:box[3]-box[1],expires:now+ttl}]:[];
    });
  }
  update(image:ImageData,now:number):CameraObject[] {
    const gray=grayscale(image),result:CameraObject[]=[];
    for(const patch of this.patches) {
      if(now>patch.expires)continue;
      let best=.76,bestBox:number[]|null=null;
      const previous=patch.object.box.map((value,i)=>value*(i%2?image.height:image.width));
      const priorSample=samples(gray,image.width,image.height,previous);
      if(priorSample){
        let dot=0;for(let i=0;i<grid*grid;i++)dot+=priorSample.values[i]*patch.values[i];
        const score=dot/(priorSample.norm*patch.norm);
        if(score>best){best=score;bestBox=previous;}
      }
      for(const scale of [.85,1,1.15]) {
        if(best>.98)break;
        const w=patch.width*scale,h=patch.height*scale;if(w<3||h<3)continue;
        for(let y=0;y+h<image.height;y+=6)for(let x=0;x+w<image.width;x+=6) {
          const box=[x,y,x+w,y+h],sample=samples(gray,image.width,image.height,box);if(!sample)continue;
          let dot=0;for(let i=0;i<grid*grid;i++)dot+=sample.values[i]*patch.values[i];
          const score=dot/(sample.norm*patch.norm);if(score>best){best=score;bestBox=box;}
        }
      }
      if(bestBox){
        patch.object={...patch.object,box:bestBox.map((v,i)=>v/(i%2?image.height:image.width))};
        result.push(patch.object);
      }
    }
    return result;
  }
}
