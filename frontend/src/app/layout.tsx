import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Spoqa Han Sans Neo (SIL OFL, src/fonts/LICENSE.txt)
const spoqa = localFont({
  variable: "--font-spoqa",
  src: [
    { path: "../fonts/SpoqaHanSansNeo-Regular.woff2", weight: "400" },
    { path: "../fonts/SpoqaHanSansNeo-Medium.woff2", weight: "500" },
    { path: "../fonts/SpoqaHanSansNeo-Bold.woff2", weight: "700" },
  ],
});

export const metadata: Metadata = {
  title: "Ask MES!",
  description: "자연어 질문을 SQL문으로 바꿔 MES 데이터를 조회하는 NL2SQL 시스템",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="ko"
      className={`${spoqa.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
