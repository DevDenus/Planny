import { Navigate, Route, Routes } from "react-router";

import { AssistantPage } from "./features/assistant/AssistantPage";
import { ChangePasswordPage } from "./features/auth/ChangePasswordPage";
import { LoginPage } from "./features/auth/LoginPage";
import { RequireSession } from "./features/auth/RequireSession";
import { BoardPage } from "./features/boards/BoardPage";
import { BoardsPage } from "./features/boards/BoardsPage";
import { CalendarPage } from "./features/calendar/CalendarPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { AppShell } from "./features/shell/AppShell";
import { TasksPage } from "./features/tasks/TasksPage";
import { ToastProvider } from "./ui";

export function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireSession />}>
          <Route path="/change-password" element={<ChangePasswordPage />} />
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/calendar" replace />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/boards" element={<BoardsPage />} />
            <Route path="/boards/:boardId" element={<BoardPage />} />
            <Route path="/assistant" element={<AssistantPage />} />
            <Route path="/assistant/:chatId" element={<AssistantPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ToastProvider>
  );
}
