import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserOut } from "@/api/schemas";

interface AuthState {
  token: string | null;
  user: UserOut | null;
  setToken: (t: string | null) => void;
  setUser: (u: UserOut | null) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setToken: (t) => set({ token: t }),
      setUser: (u) => set({ user: u }),
      clear: () => set({ token: null, user: null }),
    }),
    { name: "tg-ferma-auth" },
  ),
);
