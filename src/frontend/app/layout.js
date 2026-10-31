import "./globals.css";
import "./clinical-theme.css";
import SessionWorkspace from "./components/SessionWorkspace";
import AppShell from "./components/AppShell";

export const metadata = {
  title: "NSO AI-PC V2.2 · Clinical Decision Support",
  description: "Knowledge-guided personalization engine for clinical decision support",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Inter+Tight:wght@400;500&family=Source+Serif+4:ital,wght@0,400;1,400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body><SessionWorkspace><AppShell>{children}</AppShell></SessionWorkspace></body>
    </html>
  );
}
