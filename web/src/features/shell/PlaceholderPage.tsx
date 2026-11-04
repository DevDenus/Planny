import type { ReactNode } from "react";

import styles from "./PlaceholderPage.module.css";

export function PlaceholderPage({ title, icon }: { title: string; icon: ReactNode }) {
  return (
    <section className={styles.page}>
      <h1 className={styles.title}>{title}</h1>
      <div className={styles.empty}>
        <span className={styles.icon}>{icon}</span>
        <p>Этот раздел появится на следующих этапах</p>
      </div>
    </section>
  );
}
