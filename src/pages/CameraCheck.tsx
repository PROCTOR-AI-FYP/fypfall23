import { DeviceCamera } from '@/components/monitoring/DeviceCamera';
export function CameraCheck(){return <div className="space-y-5"><div><h1 className="text-display-lg text-(--color-text-primary)">Camera check</h1><p className="text-body-sm text-(--color-text-secondary)">Try head pose, phones and books on the camera of the device you are using.</p></div><DeviceCamera /></div>;}
