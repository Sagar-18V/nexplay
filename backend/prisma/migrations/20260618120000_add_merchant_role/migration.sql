-- CreateEnum
CREATE TYPE "Role" AS ENUM ('ADMIN', 'MERCHANT', 'VIEWER');

-- AlterTable
ALTER TABLE "merchants" ADD COLUMN     "role" "Role" NOT NULL DEFAULT 'MERCHANT';
