import { ThemeProvider as NextThemesProvider } from "next-themes";

/**
 * Thin wrapper over next-themes. It toggles `.dark` on <html>, persists
 * the choice to localStorage under `storageKey`, and defaults to the OS
 * preference when `defaultTheme="system"`. shadcn's sonner reads the same
 * provider via next-themes' useTheme().
 */
export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = "sgl-theme",
}: {
  children: React.ReactNode;
  defaultTheme?: "light" | "dark" | "system";
  storageKey?: string;
}) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme={defaultTheme}
      enableSystem
      storageKey={storageKey}
      disableTransitionOnChange
    >
      {children}
    </NextThemesProvider>
  );
}
