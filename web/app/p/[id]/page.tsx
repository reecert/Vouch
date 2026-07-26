import { notFound } from "next/navigation";

import ProfileView from "@/components/Profile";
import { listProfileIds, loadProfile } from "@/lib/data";

export const dynamicParams = false;

export function generateStaticParams() {
  return listProfileIds().map((id) => ({ id }));
}

export default async function ProfilePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const profile = loadProfile(id);
  if (!profile) notFound();
  return <ProfileView profile={profile} />;
}
