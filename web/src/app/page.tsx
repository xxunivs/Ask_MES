import { connection } from "next/server";
import Workspace from "@/components/Workspace";

// 정적 페이지면 Firebase CDN 이 1년 캐시해 재배포가 반영되지 않음
export const instant = false;

export default async function Home() {
  await connection();
  return <Workspace />;
}
