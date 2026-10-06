import type { DetectionEvent } from './types';

/** Merge committed camera/socket events with REST without losing in-flight alerts. */
export class LiveAlertFeed {
  private events=new Map<string,DetectionEvent>();
  private versions=new Map<string,number>();
  private revision=0;
  private request=0;
  private appliedRequest=0;
  private sessionId:string;
  constructor(sessionId:string){this.sessionId=sessionId;}
  beginSnapshot(){return {revision:this.revision,request:++this.request};}
  receive(event:DetectionEvent){
    if(event.sessionId!==this.sessionId)return false;
    const previous=this.events.get(event.id);
    // A repeated creation packet cannot undo a later human review.
    this.events.set(event.id,previous&&event.status==='New'&&previous.status!=='New'?{...event,status:previous.status}:event);
    this.versions.set(event.id,++this.revision);
    return true;
  }
  reconcile(token:{revision:number;request:number},snapshot:DetectionEvent[]){
    if(token.request<this.appliedRequest)return false;
    this.appliedRequest=token.request;
    const next=new Map(snapshot.filter(e=>e.sessionId===this.sessionId).map(e=>[e.id,e]));
    for(const [id,event] of this.events)if((this.versions.get(id)||0)>token.revision)next.set(id,event);
    this.events=next;
    for(const id of this.versions.keys())if(!next.has(id))this.versions.delete(id);
    return true;
  }
  list(){return [...this.events.values()].sort((a,b)=>Date.parse(b.detectedAt)-Date.parse(a.detectedAt)||a.id.localeCompare(b.id)).slice(0,500);}
}
