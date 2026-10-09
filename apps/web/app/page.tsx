import LocalDashboard from "../components/LocalDashboard";
import SavedDemo from "../components/SavedDemo";
export default function Home() {
  return process.env.NEXT_PUBLIC_DEMO_ONLY === "true" ? (
    <SavedDemo />
  ) : (
    <LocalDashboard />
  );
}
