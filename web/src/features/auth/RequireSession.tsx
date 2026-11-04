import { Navigate, Outlet, useLocation } from "react-router";

import { Banner, Button, Spinner } from "../../ui";
import { FullScreen } from "./AuthLayout";
import { useSession } from "./session";

const CHANGE_PASSWORD_PATH = "/change-password";

export function RequireSession() {
  const location = useLocation();
  const { user, signedOut, isPending, refetch } = useSession();

  if (signedOut) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (isPending) {
    return (
      <FullScreen>
        <Spinner size={28} />
      </FullScreen>
    );
  }
  if (!user) {
    return (
      <FullScreen>
        <Banner tone="error">Не удалось загрузить данные</Banner>
        <Button variant="secondary" onClick={() => void refetch()}>
          Повторить
        </Button>
      </FullScreen>
    );
  }

  const onChangePassword = location.pathname === CHANGE_PASSWORD_PATH;
  if (user.must_change_password && !onChangePassword) {
    return <Navigate to={CHANGE_PASSWORD_PATH} replace />;
  }
  if (!user.must_change_password && onChangePassword) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}
