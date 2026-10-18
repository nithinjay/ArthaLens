import { SystemStatus } from './SystemStatus';

export function App() {
  return (
    <>
      <header className="app-header">
        <h1>ArthaLens</h1>
        <p className="muted">IPO research &amp; stock intelligence for Indian markets</p>
      </header>
      <main>
        <p className="notice" role="note">
          Educational research tool. Nothing here is investment advice, and ArthaLens never submits
          IPO applications or trades on your behalf.
        </p>
        <SystemStatus />
      </main>
    </>
  );
}
