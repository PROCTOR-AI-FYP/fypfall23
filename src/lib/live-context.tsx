import { createContext,useContext,useEffect,useState,type ReactNode } from 'react';
import { subscribeToChanges } from './api';
import { useAuth } from './auth-context';

const LiveRevision = createContext(0);

export function LiveProvider({children}:{children:ReactNode}) {
  const {user,refreshUser} = useAuth();
  const userId = user?.id;
  const role = user?.role;
  const [revision,setRevision] = useState(0);
  useEffect(() => {
    if (!userId) return;
    let pending:number|undefined;
    const unsubscribe = subscribeToChanges(() => {
      if (pending!==undefined) return;
      pending=window.setTimeout(() => { pending=undefined; void refreshUser(); setRevision(value=>value+1); },150);
    });
    return () => { unsubscribe(); window.clearTimeout(pending); };
  },[userId,role,refreshUser]);
  return <LiveRevision.Provider value={revision}>{children}</LiveRevision.Provider>;
}

export function useLiveRevision() { return useContext(LiveRevision); }
