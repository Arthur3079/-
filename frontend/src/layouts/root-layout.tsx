import { Outlet } from "react-router-dom";
import { Sidebar } from "./sidebar";

export function RootLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex flex-1 flex-col overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
