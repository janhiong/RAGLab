export type Overview = {
  documents: number;
  experiments: number;
  live_generation: boolean;
};
export type Experiment = {
  id: string;
  name: string;
  status: string;
  created_at: string;
};
const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export async function request<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${base}${path}`, { signal });
  if (!response.ok)
    throw new Error(
      `API request failed (${response.status}). Check the API and database.`,
    );
  return response.json() as Promise<T>;
}
