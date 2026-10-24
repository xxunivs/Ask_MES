import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import localFont from "next/font/local";
import "./globals.css";

// Spoqa Han Sans Neo 글꼴 (SIL OFL 라이선스, src/fonts/LICENSE.txt)
const spoqa = localFont({
  variable: "--font-spoqa",
  src: [
    { path: "../fonts/SpoqaHanSansNeo-Regular.woff2", weight: "400" },
    { path: "../fonts/SpoqaHanSansNeo-Medium.woff2", weight: "500" },
    { path: "../fonts/SpoqaHanSansNeo-Bold.woff2", weight: "700" },
  ],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "NeuroFactory",
  description: "자연어 질문으로 MES 데이터를 조회하는 NL2SQL 시스템",
};

// 전체 페이지 공통 틀
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="ko"
      className={`${spoqa.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
