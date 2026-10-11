import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#121212",
        panel: "#18181B",
        line: "#27272A",
        focus: "#10B981",
        rest: "#EF4444"
      }
    }
  },
  plugins: []
};

export default config;
