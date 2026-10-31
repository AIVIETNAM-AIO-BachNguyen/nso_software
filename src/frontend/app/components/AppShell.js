"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

function NavIcon({ research = false }) {
  return <svg className="sidebar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{research ? <><path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3"/><path d="M8 15h8"/></> : <><circle cx="12" cy="7" r="3.5"/><path d="M5 21v-3a7 7 0 0 1 14 0v3M9 17h6M12 14v6"/></>}</svg>;
}

export default function AppShell({ children }) {
  const path = usePathname();
  return <div className="app-shell">
    <aside className="app-sidebar" aria-label="Main navigation">
      <Link href="/" className="app-logo" aria-label="NSO Clinical home"><svg className="sidebar-icon sidebar-menu-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg><span className="sidebar-brand">NSO Clinical</span></Link>
      <p className="nav-caption">WORKSPACE</p>
      <nav aria-label="Workspace"><Link href="/" aria-label="Patient care" title="Patient care" aria-current={path === "/" ? "page" : undefined}><NavIcon/><span className="sidebar-label">Patient care</span></Link><Link href="/research" aria-label="Research & engineering" title="Research & engineering" aria-current={path.startsWith("/research") ? "page" : undefined}><NavIcon research/><span className="sidebar-label">Research & engineering</span></Link></nav>
      <div className="sidebar-footer"><span className="status-dot" /><span className="sidebar-label">Clinical pilot</span></div>
    </aside>
    <div className="app-main"><header className="app-header"><span>{path === "/" ? "Patient care / Clinical assessment" : "Research / Study workspace"}</span><span className="workspace-tag">NSO · Decision support</span></header>{children}</div>
  </div>;
}
