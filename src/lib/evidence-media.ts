import type { CaseMedia } from './types';

/** Saved images remain reviewable when a video has not arrived or was removed. */
export function reviewImage(media:CaseMedia):{url:string;kind:'snapshot'|'record'}|null {
  if(media.clipStatus==='deleted_after_review'&&media.recordImageUrl)
    return {url:media.recordImageUrl,kind:'record'};
  if(media.snapshotUrl)return {url:media.snapshotUrl,kind:'snapshot'};
  if(media.recordImageUrl)return {url:media.recordImageUrl,kind:'record'};
  return null;
}
