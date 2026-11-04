import { CalendarDays, ListChecks, SquareKanban } from "lucide-react";
import { Navigate, Route, Routes } from "react-router";

import { ChangePasswordPage } from "./features/auth/ChangePasswordPage";
import { LoginPage } from "./features/auth/LoginPage";
import { RequireSession } from "./features/auth/RequireSession";
import { SettingsPage } from "./features/settings/SettingsPage";
import { AppShell } from "./features/shell/AppShell";
import { PlaceholderPage } from "./features/shell/PlaceholderPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireSession />}>
        <Route path="/change-password" element={<ChangePasswordPage />} />
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/calendar" replace />} />
          <Route
            path="/calendar"
            element={<PlaceholderPage title="Календарь" icon={<CalendarDays size={32} />} />}
          />
          <Route
            path="/tasks"
            element={<PlaceholderPage title="Задачи" icon={<ListChecks size={32} />} />}
          />
          <Route
            path="/boards"
            element={<PlaceholderPage title="Доски" icon={<SquareKanban size={32} />} />}
          />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
