import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { authService, type AccessTokenResponse } from "@/services/AuthService"
import { useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { useNavigate } from "react-router-dom"


export const Component = () =>{
    const [mode, setMode] = useState<"signin" | "signup">("signin")
    const [name, setName] = useState("")
    const [email, setEmail] = useState("")
    const [password, setPassword] = useState("")
    const navigate = useNavigate()


    const mutation = useMutation<AccessTokenResponse, Error>({
        mutationFn: () => mode === "signin" ? authService.signin(email, password) : authService.signup(name, email,password),
        onSuccess: () => navigate("/docs"),
    })

    function handleSubmit(e: React.FormEvent) {
        e.preventDefault()
        mutation.mutate()
    }

    return(
        <div className="flex min-h-screen items-center justify-center bg-background">
        <Card className="w-full max-w-sm">
            <CardHeader>
                <CardTitle>{mode === "signin" ? "Sign in" : "Create an account"}</CardTitle>
            </CardHeader>
            <CardContent>
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                {mode === "signup" && (
                <div className="flex flex-col gap-2">
                    <Label htmlFor="name">Name</Label>
                    <Input
                    id="name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    minLength={4}
                    maxLength={25}
                    />
                </div>
                )}

                <div className="flex flex-col gap-2">
                <Label htmlFor="email">Email</Label>
                <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                />
                </div>

                <div className="flex flex-col gap-2">
                <Label htmlFor="password">Password</Label>
                <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={6}
                />
                </div>

                {mutation.isError && (
                <p className="text-sm text-destructive">{mutation.error.message}</p>
                )}

                <Button type="submit" disabled={mutation.isPending}>
                    {mutation.isPending
                        ? "Please wait…"
                        : mode === "signin"
                        ? "Sign in"
                        : "Sign up"}
                </Button>

                <button
                    type="button"
                    className="text-sm text-muted-foreground underline underline-offset-4"
                    onClick={() => setMode(mode === "signin" ? "signup" : "signin")}
                >
                {mode === "signin"
                    ? "Need an account? Sign up"
                    : "Already have an account? Sign in"}
                </button>
            </form>
            </CardContent>
        </Card>
        </div>
    )
    
}

