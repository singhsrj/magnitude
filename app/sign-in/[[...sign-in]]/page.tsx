import { SignIn } from "@clerk/nextjs";
import { AuthShell } from "@/components/landing/AuthShell";

export default function SignInPage() {
  return (
    <AuthShell>
      <SignIn />
    </AuthShell>
  );
}
