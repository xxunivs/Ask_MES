import { connection } from "next/server";
import Workspace from "@/components/Workspace";

// 요청마다 렌더링 (정적 페이지는 Firebase CDN 이 1년 캐시)
export const instant = false;

export default async function Home() {
  await connection();
  return <Workspace />;
}
