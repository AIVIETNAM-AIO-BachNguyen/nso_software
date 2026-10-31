"use client";
import { createContext, useContext, useEffect, useRef, useState } from "react";
const Context=createContext(null);
export default function SessionWorkspace({children}) {
  const cache=useRef({});
  const [epoch,setEpoch]=useState(0);
  useEffect(()=>{
    let timer;
    const renew=()=>{clearTimeout(timer);timer=setTimeout(()=>{cache.current={};setEpoch(x=>x+1);},15*60*1000);};
    renew();window.addEventListener("pointerdown",renew);window.addEventListener("keydown",renew);
    return ()=>{clearTimeout(timer);window.removeEventListener("pointerdown",renew);window.removeEventListener("keydown",renew);};
  },[]);
  return <Context.Provider value={cache}><div key={epoch}>{children}</div></Context.Provider>;
}
export function useWorkspaceState(key,initial) {
  const cache=useContext(Context);
  const [value,setValue]=useState(()=>cache && key in cache.current ? cache.current[key] : typeof initial==="function" ? initial() : initial);
  useEffect(()=>{if(cache)cache.current[key]=value;},[cache,key,value]);
  return [value,setValue];
}
export function useWorkspaceCache(){return useContext(Context);}
