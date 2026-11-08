import { ArrowLeft, History } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { Button, EmptyState, Skeleton } from "../../ui";
import { useCurrentUser } from "../auth/session";
import { useIsPhone } from "../calendar/useIsPhone";
import { useAssistantStatus } from "./api";
import styles from "./AssistantPage.module.css";
import { ChatList } from "./ChatList";
import { ChatPane } from "./ChatPane";

export function AssistantPage() {
  const { chatId } = useParams();
  const navigate = useNavigate();
  const phone = useIsPhone();
  const { data: user } = useCurrentUser();
  const { data: status, isPending } = useAssistantStatus();
  // On a phone the history takes the place of the new chat.
  const [history, setHistory] = useState(false);
  const timeZone = user?.timezone ?? "UTC";

  if (isPending) return <Skeleton height={240} />;
  if (!status?.enabled) return <EmptyState title="Ассистент отключён" />;

  const list = (
    <ChatList
      timeZone={timeZone}
      onDeleted={(id) => {
        if (id === chatId) void navigate("/assistant", { replace: true });
      }}
      onNew={() => setHistory(false)}
    />
  );
  const pane = <ChatPane key={chatId ?? "new"} chatId={chatId} voice={status.voice} />;

  if (!phone) {
    return (
      <section className={styles.page}>
        <div className={styles.side}>{list}</div>
        {pane}
      </section>
    );
  }
  if (chatId) {
    return (
      <section className={styles.phone}>
        <Link to="/assistant" className={styles.back}>
          <ArrowLeft size={18} aria-hidden="true" /> Ассистент
        </Link>
        {pane}
      </section>
    );
  }
  return (
    <section className={styles.phone}>
      <div className={styles.bar}>
        <h1 className={styles.title}>Ассистент</h1>
        <Button
          variant="secondary"
          icon={<History size={18} />}
          onClick={() => setHistory(!history)}
        >
          История
        </Button>
      </div>
      {history ? list : pane}
    </section>
  );
}
