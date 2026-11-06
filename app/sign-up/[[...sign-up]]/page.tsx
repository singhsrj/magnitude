import { SignUp } from "@clerk/nextjs";
import { AuthShell } from "@/components/landing/AuthShell";

export default function SignUpPage() {
  return (
    <AuthShell>
      <SignUp />
    </AuthShell>
  );
}
